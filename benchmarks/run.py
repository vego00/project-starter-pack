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
import signal
import statistics
import subprocess
import sys
import time
from collections import Counter
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402
from app.config import Settings  # noqa: E402
from app.journey.design import ServiceDesign  # noqa: E402
from app.journey.design_generator import (  # noqa: E402
    MAX_ATTEMPTS,
    MAX_OUTAGE_RETRIES,
    DesignDraft,
    assemble_design,
    generate_design,
    provenance_for,
)
from app.journey.llm import EXAONE_MODEL  # noqa: E402
from app.journey.prompts import DESIGN_VERSION  # noqa: E402
from app.journey.service import JourneyService  # noqa: E402
from app.journey.services import JourneyDeps, StartFailure, build_deps  # noqa: E402
from app.journey.state import JourneyAction, JourneyState, ProjectSpec  # noqa: E402
from app.registry.loader import Registry, load_registry  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from pydantic import TypeAdapter, ValidationError  # noqa: E402

from benchmarks.evaluators.design import design_checks  # noqa: E402
from benchmarks.evaluators.intake import IntakeCase, evaluate  # noqa: E402

CASES_DIR = ROOT / "benchmarks" / "datasets" / "cases"
REPORTS_DIR = ROOT / "reports"
ACTION = TypeAdapter(JourneyAction)
CALLS_PER_DESIGN = MAX_ATTEMPTS + MAX_OUTAGE_RETRIES  # The most one design can cost.
MAX_STEPS = 40
DEFAULT_BUDGET = 60  # Design calls per evaluation, a starting cap (SD-008 plan).
DEFAULT_GAP_S = 20  # Between runs with a real model; fewer 429s were seen with it.


class CountingDesigner:
    """Counts design calls so a run stops before the budget instead of after it.

    With record=True it also keeps every attempt: the problems it was sent, the draft it returned,
    and what the validator said. A rejected draft can then be re-checked with rescore.py later,
    without another model call. A draft that broke the output contract has no draft to keep, only
    the failed fields, because the model client raises before returning it.
    """

    def __init__(self, inner, record=False):
        self.inner = inner
        self.calls = 0
        self.record = record
        self.attempts: list[dict[str, Any]] = []

    def draft(self, state, constraints, problems):
        self.calls += 1
        if not self.record:
            return self.inner.draft(state, constraints, problems)
        entry: dict[str, Any] = {
            "call": self.calls,
            "prompt_version": DESIGN_VERSION,
            "problems_in": list(problems),
        }
        self.attempts.append(entry)
        try:
            attempt = self.inner.draft(state, constraints, problems)
        except ValidationError as exc:
            entry["outcome"] = "contract_error"
            entry["contract_fields"] = [
                ".".join(map(str, e["loc"])) + ":" + e["type"]
                for e in exc.errors(include_input=False, include_url=False)
            ]
            raise
        except Exception as exc:
            entry.update(
                outcome="call_failed",
                error_type=type(exc).__name__,
                error_code=getattr(exc, "code", None),
            )
            raise
        provenance = provenance_for(
            state,
            constraints,
            source="model",
            model_id=attempt.model_id,
            prompt_version=DESIGN_VERSION,
        )
        fields = {name: getattr(attempt.draft, name) for name in DesignDraft.model_fields}
        issues = assemble_design(fields, constraints, provenance).validation or []
        entry.update(
            outcome="rejected" if any(i.severity == "error" for i in issues) else "accepted",
            model_id=attempt.model_id,
            input_tokens=attempt.input_tokens,
            output_tokens=attempt.output_tokens,
            rules=sorted({i.rule_id for i in issues if i.severity == "error"}),
            warnings=sorted({i.rule_id for i in issues if i.severity == "warning"}),
            draft=attempt.draft.model_dump(mode="json"),
            constraints=constraints.model_dump(mode="json"),
            provenance=provenance.model_dump(mode="json"),
        )
        return attempt


def attempt_tokens(attempts: list[dict]) -> dict[str, int | None]:
    """Summed over the drafts that came back. None when a draft reported no count."""
    drafts = [a for a in attempts if a.get("outcome") in ("accepted", "rejected")]
    totals: dict[str, int | None] = {}
    for key in ("input_tokens", "output_tokens"):
        values = [a.get(key) for a in drafts]
        totals[key] = None if any(v is None for v in values) else sum(values)
    return totals


class ScenarioUnanswered(Exception):
    pass


class CallBudgetExceeded(BaseException):
    pass


class CountingStartWriter:
    def __init__(self, inner, limit=20):
        self.inner, self.limit = inner, limit
        self.calls = 0
        self.failures = 0
        self.attempts = []

    def _call(self, method, *args, **kwargs):
        if self.calls >= self.limit:
            raise CallBudgetExceeded()
        self.calls += 1
        started = time.perf_counter()
        event = {"method": method, "source": "error"}
        try:
            reply = getattr(self.inner, method)(*args, **kwargs)
            failed = reply is None or isinstance(reply, StartFailure)
            self.failures += failed
            if isinstance(reply, StartFailure):
                event["reason"] = reply.reason
            event.update(
                source="unavailable" if failed else "model" if reply.model_id else "mock",
                model_id=getattr(reply, "model_id", None),
                input_tokens=getattr(reply, "input_tokens", None),
                output_tokens=getattr(reply, "output_tokens", None),
            )
            return reply
        finally:
            event["seconds"] = round(time.perf_counter() - started, 3)
            self.attempts.append(event)

    def write(self, *args, **kwargs):
        return self._call("write", *args, **kwargs)

    def recommend_gcb(self, *args, **kwargs):
        return self._call("recommend_gcb", *args, **kwargs)


class _Lines(logging.Handler):
    def __init__(self):
        super().__init__(logging.INFO)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage())


def design_model(settings: Settings) -> str:
    """The model that writes the design: with K-EXAONE as the service model it writes it too."""
    if settings.provider == "exaone":
        return settings.exaone_model or EXAONE_MODEL
    return settings.gemini_design_model or settings.gemini_model or "-"


def load_cases(names: list[str] | None = None) -> list[dict[str, Any]]:
    paths = sorted(CASES_DIR.glob("*.yaml"))
    cases = [yaml.safe_load(path.read_text("utf-8")) for path in paths]
    for case in cases:
        if case.get("evaluation") == "intake":
            IntakeCase.model_validate(case)
        else:
            ProjectSpec.model_validate(case["spec"])
    if len({c["id"] for c in cases}) != len(cases):
        raise ValueError("Duplicate case id")
    if names and set(names) - {case["id"] for case in cases}:
        raise ValueError("Unknown case id")
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
    if case.get("evaluation") == "design":
        fixed = case["selection"].get(card_id)
        if fixed not in open_options:
            raise ScenarioUnanswered(f"fixed_choice_unavailable:{card_id}")
        return fixed
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
        elif kind == "fork":
            action = {"action": "plan_deploy"}
        elif kind == "done":
            break
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
    else:
        stopped_at = {"prompt": "step_limit"}
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
        design = service.design(view.journey_id)
        result["design"] = design_metrics(design)
        result["artifact"] = design.model_dump(mode="json")
        # Blank info takes card defaults on the way (ADR-024), so the design reads the final spec.
        final = JourneyState.model_validate(service._snapshot(view.journey_id).values)
        result["checks"] = design_checks(
            design,
            service.package(view.journey_id),
            registry,
            case["spec"]["idea"],
            case=case,
            final_spec=final.project_spec,
        )
    result["outcome"] = "completed" if view.design else "scenario_unanswered"
    if stopped_at and stopped_at["prompt"] == "step_limit":
        result["outcome"] = "step_limit"
    return result


def run_blank(case: dict, deps: JourneyDeps, registry: Registry) -> dict[str, Any]:
    state = JourneyState(journey_id=uuid4(), project_spec=ProjectSpec(**case["spec"]))
    outcome = generate_design(
        state, registry, deps.designer, attempts=MAX_ATTEMPTS, outage_retries=MAX_OUTAGE_RETRIES
    )
    return {
        "design": design_metrics(outcome.design.current),
        "tokens": [outcome.input_tokens, outcome.output_tokens],
        "outcome": "completed",
        "artifact": outcome.design.current.model_dump(mode="json"),
        "checks": design_checks(outcome.design.current, case=case, fixed_choices=False),
    }


def _snapshot_start(view):
    return {
        "fields": {f.name: f.model_dump() for f in view.start.fields},
        "asks": view.start.chat[-1].asks if view.start.chat else None,
        "missing": view.start.missing,
        "rejected": view.start.chat[-1].rejected if view.start.chat else [],
    }


def run_intake(case, deps, registry):
    service = JourneyService(registry, InMemorySaver(), deps)
    failures_before = getattr(deps.start_writer, "failures", 0)
    view = service.start(ProjectSpec(idea=case["idea"]))
    snapshots = {"initial": _snapshot_start(view)}
    events = []
    outcome = "completed"
    if deps.start_writer is None:
        outcome = "mock_unavailable"
    elif getattr(deps.start_writer, "failures", 0) > failures_before:
        outcome = "product_error"
    else:
        for turn in case.get("turns", []):
            view = service.send_start_message(
                view.journey_id, view.start.revision, turn["message"], turn.get("focus")
            )
            snapshots[turn["id"]] = _snapshot_start(view)
        # Reply only by stable field ID, and never invent an answer for the scenario.
        for _ in range(MAX_STEPS):
            snap = _snapshot_start(view)
            asks = snap["asks"]
            if not asks:
                break
            if asks not in case.get("answers", {}):
                events.append({"type": "unanswered_question", "field": asks})
                outcome = "scenario_unanswered"
                break
            message = case["answers"][asks]
            view = service.send_start_message(view.journey_id, view.start.revision, message, asks)
            events.append({"type": "answered", "field": asks})
        else:
            outcome = "step_limit"
    snapshots["final"] = _snapshot_start(view)
    target = case.get("continue_to")
    if target and outcome == "completed" and not view.start.missing:
        view = service.act(
            view.journey_id, view.revision, ACTION.validate_python(view.start.submit)
        )
        for _ in range(MAX_STEPS):
            prompt = view.prompt or {}
            card = prompt.get("card", {})
            if card.get("card_id") == target:
                snapshots[f"card:{target}"] = {
                    "fields": {item["name"]: item for item in card.get("signals", [])}
                }
                break
            if prompt.get("type") == "fork":
                action = {"action": "plan_deploy"}
            elif card.get("card_id") in case.get("selection", {}):
                action = {"action": "select", "option_id": case["selection"][card["card_id"]]}
            else:
                events.append(
                    {
                        "type": "unexpected_prompt",
                        "prompt": prompt.get("type"),
                        "card_id": card.get("card_id"),
                    }
                )
                outcome = "scenario_unanswered"
                break
            view = service.act(view.journey_id, view.revision, ACTION.validate_python(action))
        else:
            outcome = "step_limit"
    if view.start and view.start.missing and outcome == "completed":
        outcome = "scenario_unanswered"
    checks = evaluate(case["checks"], snapshots)
    # A question about a field already filled at that checkpoint is redundant.
    for name, snap in snapshots.items():
        asks = snap.get("asks")
        if asks and snap["fields"].get(asks, {}).get("value") is not None:
            checks.append({"id": "redundant_question", "checkpoint": name, "status": "fail"})
    if outcome == "mock_unavailable":
        for check in checks:
            check["status"] = "not_run"
    return {
        "journey_id": str(view.journey_id),
        "outcome": outcome,
        "snapshots": snapshots,
        "events": events,
        "checks": checks,
    }


class CaseTimeout(BaseException):
    pass


@contextmanager
def deadline(seconds):
    # The CLI runs on the main thread on Linux/WSL. Interrupt the call, not a detached thread.
    previous = signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(CaseTimeout()))
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def run_case(
    case: dict, mode: str, deps: JourneyDeps, registry: Registry, timeout_s: float = 600
) -> dict[str, Any]:
    if mode not in {"flow", "blank", "intake"}:
        raise ValueError("Unknown evaluation mode")
    lines = _Lines()
    logger = logging.getLogger("app.journey")
    old_level = logger.level
    logger.addHandler(lines)
    logger.setLevel(logging.INFO)
    counter = CountingDesigner(deps.designer, record=True) if deps.designer else None
    if counter:
        deps = replace(deps, designer=counter)
    if deps.start_writer and not isinstance(deps.start_writer, CountingStartWriter):
        deps = replace(deps, start_writer=CountingStartWriter(deps.start_writer))
    start_before = getattr(deps.start_writer, "calls", 0)
    started = time.perf_counter()
    try:
        with deadline(timeout_s):
            execute = {"flow": run_flow, "blank": run_blank, "intake": run_intake}[mode]
            body = execute(case, deps, registry)
    except ScenarioUnanswered as exc:
        body = {"outcome": "scenario_unanswered", "reason": str(exc)}
    except CallBudgetExceeded:
        body = {"outcome": "budget_exhausted"}
    except (CaseTimeout, TimeoutError):
        body = {"outcome": "timeout"}
    except Exception as exc:
        body = {
            "outcome": "product_error",
            "error_type": type(exc).__name__,
            "error_code": getattr(exc, "code", None),
        }
    finally:
        logger.removeHandler(lines)
        logger.setLevel(old_level)
    findings = log_findings(lines.lines)
    calls = counter.calls if counter else 0
    return {
        "case": case["id"],
        "case_status": case["status"],
        "mode": mode,
        "family": case.get("family", case["id"]),
        "evaluation": "intake" if mode == "intake" else "design",
        "seconds": round(time.perf_counter() - started, 3),
        "design_calls": calls,
        "single_draft_pass": body.get("design", {}).get("source") == "model"
        and calls == 1
        and not any(findings.values()),
        "start_calls": getattr(deps.start_writer, "calls", 0) - start_before,
        "start_attempts": getattr(deps.start_writer, "attempts", [])[start_before:],
        "http_attempts": None,
        "design_attempts": counter.attempts if counter else [],
        "design_tokens": attempt_tokens(counter.attempts) if counter else {},
        "human_review": [
            {"criterion": item, "status": "pending"} for item in case.get("human_review", [])
        ],
        **findings,
        **body,
    }


def _median(values: list[float]) -> float | str:
    return statistics.median(values) if values else "-"


def _row(cells: list[Any]) -> str:
    return "| " + " | ".join(str(cell) for cell in cells) + " |"


def summarize(results: list[dict], meta: dict) -> str:
    lines = [f"# 평가 실행 {meta['stamp']}", ""]
    lines += [f"- {key}: {value}" for key, value in meta.items() if key != "stamp"]
    head = ["사례", "흐름", "회수", "맞춤 설계", "단일 draft 통과", "분기 있음", "반복 한도 있음",
            "조건 연결선(중앙값)", "걸린 규칙", "429", "초(중앙값)"]  # fmt: skip
    lines += ["", _row(head), _row(["---"] * len(head))]
    groups: dict[tuple, list[dict]] = {}
    for result in results:
        if result["mode"] == "intake":
            continue
        groups.setdefault((result["case"], result["mode"]), []).append(result)
    for (case_id, mode), runs in groups.items():
        model = [r["design"] for r in runs if r.get("design", {}).get("source") == "model"]
        first = sum(1 for r in runs if r.get("single_draft_pass"))
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
    flows = [r for r in results if r["mode"] == "flow" and "skipped" in r]
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
    lines += [
        "",
        "단일 draft 통과는 designer.draft 1회에 성공한 결과다. SDK 내부 HTTP 재시도는 미계측이다.",
        "mock은 파이프라인 검증이며 모델 품질 결과가 아니다. 같은 family의 변형은 새 사용자 시나리오가 아니다.",
    ]
    head = ["평가", "사례", "family", "완료 상태", "자동 pass/fail/not_run", "사람 평가 대기"]
    lines += ["", _row(head), _row(["---"] * len(head))]
    for r in results:
        counts = Counter(c["status"] for c in r.get("checks", []))
        lines.append(
            _row(
                [
                    r.get("evaluation"),
                    r["case"],
                    r.get("family"),
                    r.get("outcome"),
                    "/".join(str(counts[k]) for k in ("pass", "fail", "not_run")),
                    len(r.get("human_review", [])),
                ]
            )
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
    parser.add_argument(
        "--intake-budget",
        type=int,
        default=20,
        help="max start writer calls across this evaluation; SDK retries excluded",
    )
    parser.add_argument("--mock", action="store_true", help="ignore provider/decider in .env")
    parser.add_argument(
        "--allow-real", action="store_true", help="explicitly enable configured APIs"
    )
    parser.add_argument("--timeout", type=float, default=600, help="seconds per case (Linux/WSL)")
    args = parser.parse_args(argv)

    overrides = {"gemini_design_model": args.design_model} if args.design_model else {}
    if args.mock:
        overrides.update(provider="mock", decider="mock")
    settings = Settings(**overrides)
    if not args.allow_real and (settings.provider != "mock" or settings.decider != "mock"):
        parser.error(
            "Real APIs require --allow-real after checking environment and budget; use --mock"
        )
    if not re.fullmatch(r"[A-Za-z0-9_.-]*", args.label):
        parser.error("label must contain only letters, digits, _, . or -")
    if args.gap is not None and args.gap < 0:
        parser.error("gap must be nonnegative")
    if args.runs < 1 or args.timeout <= 0 or args.budget < 0 or args.intake_budget < 0:
        parser.error("runs/timeout must be positive, budget nonnegative")
    modes = args.modes.split(",")
    if set(modes) - {"flow", "blank", "intake"}:
        parser.error("modes: flow,blank,intake")

    cases = load_cases(args.cases.split(",") if args.cases else None)
    if not any(
        (case.get("evaluation") == "intake") == (mode == "intake")
        for case in cases
        for mode in modes
    ):
        parser.error("No cases match the requested modes")
    registry = load_registry()
    deps = build_deps(settings, registry)
    start_counter = (
        CountingStartWriter(deps.start_writer, args.intake_budget) if deps.start_writer else None
    )
    # Intake measures extraction. Later card recommendations stay mock and cannot spend API calls.
    intake_deps = JourneyDeps(start_writer=start_counter)
    counter = CountingDesigner(deps.designer) if deps.designer else None
    if counter:
        deps = replace(deps, designer=counter)
    gap = args.gap if args.gap is not None else (DEFAULT_GAP_S if counter else 0)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    meta = {
        "stamp": stamp,
        "commit": _commit(),
        "working_tree_dirty": bool(
            subprocess.run(
                # Untracked files such as new reports do not change what ran.
                ["git", "status", "--porcelain", "--untracked-files=no"],
                cwd=ROOT,
                capture_output=True,
                text=True,
            ).stdout.strip()
        ),
        "provider": settings.provider,
        "decider": f"{settings.decider} ({settings.jev_route})",
        "design_model": design_model(settings),
        "prompt": DESIGN_VERSION,
        "runs": args.runs,
        "label": args.label or "-",
    }
    results: list[dict] = []
    for case in cases:
        for mode in modes:
            if (case.get("evaluation") == "intake") != (mode == "intake"):
                continue
            for run in range(1, args.runs + 1):
                if mode != "intake" and counter and counter.calls + CALLS_PER_DESIGN > args.budget:
                    meta["stopped"] = f"설계 호출 예산 {args.budget}회에 닿아 멈춤"
                    break
                if results and gap:
                    time.sleep(gap)
                result = {
                    "run": run,
                    **run_case(
                        case,
                        mode,
                        intake_deps if mode == "intake" else deps,
                        registry,
                        args.timeout,
                    ),
                }
                results.append(result)
                source = result.get("design", {}).get("source", "-")
                print(f"{case['id']} {mode} {run}: {source} {result['seconds']}s", flush=True)
    meta["design_calls"] = counter.calls if counter else 0
    tokens = [r.get("design_tokens") or {} for r in results if r.get("mode") != "intake"]
    for key in ("input_tokens", "output_tokens"):
        values = [t.get(key) for t in tokens if t]
        meta[f"design_{key}"] = sum(values) if values and None not in values else "미확인"
    # Prices change and are not in the repo, so cost is not computed here.
    meta["design_cost"] = "미확인"
    meta["start_calls"] = start_counter.calls if start_counter else 0
    meta["intake_budget"] = args.intake_budget
    meta["intake_card_dependencies"] = "mock (extraction only)"

    out = REPORTS_DIR / (f"{stamp}-{args.label}" if args.label else stamp)
    out.mkdir(parents=True, exist_ok=True)
    payload = json.dumps({"meta": meta, "results": results}, ensure_ascii=False, indent=1)
    (out / "results.json").write_text(payload, "utf-8")
    (out / "summary.md").write_text(summarize(results, meta), "utf-8")
    print(out / "summary.md")
    return out


if __name__ == "__main__":
    main()
