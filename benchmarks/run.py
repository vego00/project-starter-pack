"""Runs the fixed evaluation cases against the real journey and reports what came out.

From the repository root (WSL):
    uv run --locked python benchmarks/run.py --cases C1,C4 --modes flow,blank --runs 3

`flow` walks the card journey with the case's choices. `blank` drafts a design with no decisions.
Real models follow `.env` (APP_PROVIDER=gemini, APP_DECIDER=jev); with mock the run still works,
which is what CI checks. Results go to `reports/<stamp>/`: `summary.md` is kept, `results.json`
is not committed. Logged lines carry rule ids and HTTP statuses only, never user text.
"""

import argparse
import json
import logging
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

import yaml  # noqa: E402
from app.config import Settings  # noqa: E402
from app.journey.design import ServiceDesign  # noqa: E402
from app.journey.design_generator import (  # noqa: E402
    MAX_ATTEMPTS,
    MAX_OUTAGE_RETRIES,
    generate_design,
)
from app.journey.prompts import DESIGN_VERSION  # noqa: E402
from app.journey.service import JourneyService  # noqa: E402
from app.journey.services import JourneyDeps, build_deps  # noqa: E402
from app.journey.state import JourneyAction, JourneyState, ProjectSpec  # noqa: E402
from app.registry.loader import Registry, load_registry  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from pydantic import TypeAdapter  # noqa: E402

CASES_DIR = ROOT / "benchmarks" / "datasets" / "cases"
REPORTS_DIR = ROOT / "reports"
ACTION = TypeAdapter(JourneyAction)
CALLS_PER_DESIGN = MAX_ATTEMPTS + MAX_OUTAGE_RETRIES  # The most one design can cost.
MAX_STEPS = 40
DEFAULT_BUDGET = 60  # Design calls per evaluation, a starting cap (SD-008 plan).
DEFAULT_GAP_S = 20  # Between runs with a real model; fewer 429s were seen with it.


class CountingDesigner:
    """Counts design calls so a run stops before the budget instead of after it."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0

    def draft(self, *args, **kwargs):
        self.calls += 1
        return self.inner.draft(*args, **kwargs)


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def load_cases(names: list[str] | None = None) -> list[dict[str, Any]]:
    paths = sorted(CASES_DIR.glob("*.yaml"))
    cases = [yaml.safe_load(path.read_text("utf-8")) for path in paths]
    return [case for case in cases if names is None or case["id"] in names]


def design_metrics(design: ServiceDesign) -> dict[str, Any]:
    edges = design.workflow.edges
    outgoing = Counter(edge.source for edge in edges)
    kinds = Counter(node.kind for node in design.nodes)
    return {
        "source": design.provenance.source,
        "agent": kinds["agent"],
        "human": kinds["human"],
        "code": kinds["code"],
        "edges": len(edges),
        "conditioned_edges": sum(edge.condition is not None for edge in edges),
        "failure_edges": sum(edge.on_failure for edge in edges),
        "branch_nodes": sum(count > 1 for count in outgoing.values()),
        "loop_limits": len(design.workflow.loop_limits),
        "tools": dict(Counter(tool.access for node in design.nodes for tool in node.tools)),
        "unknowns": len(design.unknowns),
        "warnings": sorted(
            {issue.rule_id for issue in design.validation or [] if issue.severity == "warning"}
        ),
    }


def _quoted(text: str) -> list[str]:
    return re.findall(r"'([^']+)'", text)


def log_findings(lines: list[str]) -> dict[str, Any]:
    joined = " ".join(lines)
    return {
        "failed_rules": [_quoted(m) for m in re.findall(r"rules=\[([^\]]*)\]", joined)],
        "contract_fields": [_quoted(m) for m in re.findall(r"fields=\[([^\]]*)\]", joined)],
        "http_status": re.findall(r"status=(\d+)", joined),
    }


def _choose(case: dict, card: dict, registry: Registry) -> str:
    """The case's choice, else the recommendation, else the card's default; never a blocked one."""
    card_id = card["card_id"]
    open_options = [view["option"]["id"] for view in card["options"] if not view["blocked_reason"]]
    option = case["selection"].get(card_id) or card["recommendation"]["option_id"]
    option = option or registry.card(card_id).default_recommendation.option
    return option if option in open_options else open_options[0]


def run_flow(case: dict, deps: JourneyDeps, registry: Registry) -> dict[str, Any]:
    service = JourneyService(registry, InMemorySaver(), deps)
    view = service.start(ProjectSpec(**case["spec"]))
    asked: list[str] = []
    recommendations: dict[str, Any] = {}
    stopped_at = None
    for _ in range(MAX_STEPS):
        prompt = view.prompt
        if prompt is None:
            break
        kind = prompt["type"]
        if kind == "gcb":
            action = {"action": "gcb", **prompt["draft"]}
        elif kind == "clarify":
            action = {"action": "clarify", "answers": {}}
        elif kind == "decision":
            card = prompt["card"]
            asked.append(card["card_id"])
            rec = card["recommendation"]
            recommendations[card["card_id"]] = [rec["option_id"], rec["confidence"]]
            action = {"action": "select", "option_id": _choose(case, card, registry)}
        else:
            issues = [issue["rule_id"] for issue in prompt.get("issues", [])]
            stopped_at = {"prompt": kind, "rules": issues}
            break
        view = service.act(view.journey_id, view.revision, ACTION.validate_python(action))
    skipped = {c.card_id: c.skip_confidence for c in view.cards if c.state == "skipped"}
    agreed = [
        recommendations[card_id][0] == option
        for card_id, option in case["selection"].items()
        if card_id in recommendations
    ]
    result: dict[str, Any] = {
        "journey_id": str(view.journey_id),
        "status": view.status,
        "stopped_at": stopped_at,
        "asked": asked,
        "skipped": skipped,
        "must_ask_missed": [
            card_id for card_id in case.get("must_ask", []) if card_id not in asked
        ],
        "recommendations": recommendations,
        "recommendation_agreed": [sum(agreed), len(agreed)],
    }
    if view.design is not None:
        result["design"] = design_metrics(service.design(view.journey_id))
    return result


def run_blank(case: dict, deps: JourneyDeps, registry: Registry) -> dict[str, Any]:
    state = JourneyState(journey_id=uuid4(), project_spec=ProjectSpec(**case["spec"]))
    outcome = generate_design(
        state, registry, deps.designer, attempts=MAX_ATTEMPTS, outage_retries=MAX_OUTAGE_RETRIES
    )
    return {
        "design": design_metrics(outcome.design.current),
        "tokens": [outcome.input_tokens, outcome.output_tokens],
    }


def run_case(case: dict, mode: str, deps: JourneyDeps, registry: Registry) -> dict[str, Any]:
    """One run of one case, with the journey's log lines collected around it."""
    lines = _Lines()
    logger = logging.getLogger("app.journey")
    logger.addHandler(lines)
    logger.setLevel(logging.INFO)
    calls_before = getattr(deps.designer, "calls", 0)
    started = time.perf_counter()
    try:
        body = run_flow(case, deps, registry) if mode == "flow" else run_blank(case, deps, registry)
    finally:
        logger.removeHandler(lines)
    return {
        "case": case["id"],
        "case_status": case["status"],
        "mode": mode,
        "seconds": round(time.perf_counter() - started, 1),
        "design_calls": getattr(deps.designer, "calls", 0) - calls_before,
        **log_findings(lines.lines),
        **body,
    }


def _median(values: list[float]) -> float | str:
    return statistics.median(values) if values else "-"


def _row(cells: list[Any]) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def summarize(results: list[dict], meta: dict) -> str:
    lines = [f"# 평가 실행 {meta['stamp']}", ""]
    lines += [f"- {key}: {value}" for key, value in meta.items() if key != "stamp"]
    head = ["사례", "흐름", "회수", "맞춤 설계", "첫 시도 통과", "분기 있음", "반복 한도 있음",
            "조건 연결선(중앙값)", "걸린 규칙", "429", "초(중앙값)"]  # fmt: skip
    lines += ["", _row(head), _row(["---"] * len(head))]
    groups: dict[tuple, list[dict]] = {}
    for result in results:
        groups.setdefault((result["case"], result["mode"]), []).append(result)
    for (case_id, mode), runs in groups.items():
        model = [r["design"] for r in runs if r.get("design", {}).get("source") == "model"]
        first = sum(
            1
            for r in runs
            if r.get("design", {}).get("source") == "model" and not r["failed_rules"]
        )
        rules = Counter(rule for r in runs for attempt in r["failed_rules"] for rule in attempt)
        top = ", ".join(f"{rule} {count}" for rule, count in rules.most_common(4)) or "-"
        lines.append(
            _row(
                [
                    f"{case_id} ({runs[0]['case_status']})",
                    mode,
                    len(runs),
                    f"{len(model)}/{len(runs)}",
                    f"{first}/{len(runs)}",
                    f"{sum(d['branch_nodes'] > 0 for d in model)}/{len(model)}",
                    f"{sum(d['loop_limits'] > 0 for d in model)}/{len(model)}",
                    _median([d["conditioned_edges"] for d in model]),
                    top,
                    sum(r["http_status"].count("429") for r in runs),
                    _median([r["seconds"] for r in runs]),
                ]
            )
        )
    flows = [r for r in results if r["mode"] == "flow"]
    if flows:
        head = [
            "사례",
            "회",
            "물은 카드",
            "뺀 카드",
            "꼭 물을 카드 누락",
            "추천이 사례 선택과 같음",
        ]
        lines += ["", _row(head), _row(["---"] * len(head))]
        for r in flows:
            skipped = ", ".join(f"{card} {conf:.2f}" for card, conf in r["skipped"].items())
            agreed = r["recommendation_agreed"]
            missed = ", ".join(r["must_ask_missed"]) or "0"
            lines.append(
                _row(
                    [
                        r["case"],
                        r["run"],
                        len(r["asked"]),
                        skipped or "-",
                        missed,
                        f"{agreed[0]}/{agreed[1]}",
                    ]
                )  # fmt: skip
            )
    lines += ["", "횟수가 작아 1~2회 차이는 잡음으로 본다. 원자료는 같은 폴더의 results.json."]
    return "\n".join(lines) + "\n"


def _commit() -> str:
    try:
        done = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True
        )
    except OSError:
        return "unknown"
    return done.stdout.strip() or "unknown"


def main(argv: list[str] | None = None) -> Path:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cases", help="comma-separated case ids; all by default")
    parser.add_argument("--modes", default="flow,blank")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--design-model", help="overrides APP_GEMINI_DESIGN_MODEL for this run")
    parser.add_argument("--budget", type=int, default=DEFAULT_BUDGET, help="max design calls")
    parser.add_argument("--gap", type=float, help="seconds between runs")
    parser.add_argument("--label", default="")
    args = parser.parse_args(argv)

    overrides = {"gemini_design_model": args.design_model} if args.design_model else {}
    settings = Settings(**overrides)
    registry = load_registry()
    deps = build_deps(settings, registry)
    counter = CountingDesigner(deps.designer) if deps.designer else None
    if counter:
        deps = replace(deps, designer=counter)
    gap = args.gap if args.gap is not None else (DEFAULT_GAP_S if counter else 0)
    cases = load_cases(args.cases.split(",") if args.cases else None)

    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    meta = {
        "stamp": stamp,
        "commit": _commit(),
        "provider": settings.provider,
        "decider": f"{settings.decider} ({settings.jev_route})",
        "design_model": settings.gemini_design_model or settings.gemini_model or "-",
        "prompt": DESIGN_VERSION,
        "runs": args.runs,
        "label": args.label or "-",
    }
    results: list[dict] = []
    for case in cases:
        for mode in args.modes.split(","):
            for run in range(1, args.runs + 1):
                if counter and counter.calls + CALLS_PER_DESIGN > args.budget:
                    meta["stopped"] = f"설계 호출 예산 {args.budget}회에 닿아 멈춤"
                    break
                if results and gap:
                    time.sleep(gap)
                result = {"run": run, **run_case(case, mode, deps, registry)}
                results.append(result)
                source = result.get("design", {}).get("source", "-")
                print(f"{case['id']} {mode} {run}: {source} {result['seconds']}s", flush=True)
    meta["design_calls"] = counter.calls if counter else 0

    out = REPORTS_DIR / (f"{stamp}-{args.label}" if args.label else stamp)
    out.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=1)
    (out / "results.json").write_text(payload, "utf-8")
    (out / "summary.md").write_text(summarize(results, meta), "utf-8")
    print(out / "summary.md")
    return out


if __name__ == "__main__":
    main()
