"""How long a person waits for each card after answering, and for the design after the last
answer, read from a journey's trace.

Each request runs the graph from one wait to the next, so the trace splits into runs at the
waiting nodes. A card's options are visible when its run reaches `present`; its recommendation
is visible when the run that called its models does. The three preparers run in parallel, so a
run counts the longest of them. The completion screen is visible when the run that wrote the
decision summary (`composer`) ends; the design when the run with `designer` does. Only node time
is counted: HTTP and checkpoint writes are not.

    uv run --project backend python benchmarks/card_wait.py --mock [--model-delay 0.5]
        [--design-delay 3]
    uv run --project backend python benchmarks/card_wait.py --database-url URL --journey-id ID

The second form only reads the journey. Mock runs and simulated delays are not real model times.
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path
from typing import Any
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.journey.deciders.mock import MockDecider  # noqa: E402
from app.journey.graph import PREPARERS, journey_config  # noqa: E402
from app.journey.service import JourneyService  # noqa: E402
from app.journey.services import JourneyDeps, MockAdvisor  # noqa: E402
from app.journey.state import JourneyAction, ProjectSpec  # noqa: E402
from app.registry.loader import load_registry  # noqa: E402
from langgraph.checkpoint.memory import InMemorySaver  # noqa: E402
from langgraph.checkpoint.postgres import PostgresSaver  # noqa: E402
from psycopg import connect  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402
from pydantic import TypeAdapter  # noqa: E402

ACTION = TypeAdapter(JourneyAction)

WAITING_NODES = {
    "gcb_gate",
    "clarify_question",
    "decision_gate",
    "design_gate",
    "issue_gate",
    "fork_gate",
    "done_gate",
}
SPEC = {
    "idea": "강의 자료를 찾아 답하는 멀티 에이전트 서비스",
    "goal": "수강생이 근거와 함께 답을 찾을 수 있는 상태",
    "deployment_target": "small_group",
    "has_gpu": False,
}
MAX_STEPS = 80


def runs(trace: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """One list per request: a resumed waiting node starts a new run."""
    split: list[list[dict[str, Any]]] = []
    for event in trace:
        if event["node"] in WAITING_NODES or not split:
            split.append([])
        split[-1].append(event)
    return split


def run_ms(run: list[dict[str, Any]]) -> float:
    parallel = [e["latency_ms"] for e in run if e["node"] in PREPARERS]
    serial = sum(e["latency_ms"] for e in run if e["node"] not in PREPARERS)
    return serial + max(parallel, default=0.0)


def card_waits(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per card shown: when its options and when its recommendation became visible (ms)."""
    waits: list[dict[str, Any]] = []
    for run in runs(trace):
        nodes = {e["node"] for e in run}
        if "present" not in nodes:
            continue
        prepare_only = run[0]["node"] == "decision_gate" and "controller" not in nodes
        if prepare_only and waits and nodes & set(PREPARERS):
            # A `prepare` request: the card on screen gets its recommendation now.
            waits[-1]["recommendation_ms"] = waits[-1]["options_ms"] + run_ms(run)
            continue
        ms = run_ms(run)
        waits.append(
            {
                "options_ms": ms,
                "recommendation_ms": ms,
                "models_in_run": bool(nodes & set(PREPARERS)),
            }
        )
    return waits


def design_waits(trace: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per design made: when the completion screen and when the design became visible (ms)."""
    waits: list[dict[str, Any]] = []
    for run in runs(trace):
        nodes = {e["node"] for e in run}
        if "composer" in nodes:
            ms = run_ms(run)
            waits.append({"screen_ms": ms, "design_ms": ms if "designer" in nodes else None})
        elif run[0]["node"] == "design_gate" and "designer" in nodes and waits:
            # A `design` request: the screen opened before it, the design arrives now.
            waits[-1]["design_ms"] = waits[-1]["screen_ms"] + run_ms(run)
    return waits


def summary(waits: list[dict[str, Any]]) -> dict[str, Any]:
    def median(key: str) -> float | None:
        values = [w[key] for w in waits]
        return round(statistics.median(values), 1) if values else None

    return {
        "cards": len(waits),
        "options_ms_median": median("options_ms"),
        "recommendation_ms_median": median("recommendation_ms"),
        "options_ms_max": round(max((w["options_ms"] for w in waits), default=0.0), 1),
    }


class DelayedAdvisor(MockAdvisor):
    def __init__(self, delay: float):
        self.delay = delay

    def advise(self, state, card):
        time.sleep(self.delay)
        return super().advise(state, card)


class DelayedDecider(MockDecider):
    def __init__(self, delay: float):
        super().__init__()
        self.delay = delay

    def decide(self, state, question):
        if question.id.startswith("recommend."):
            time.sleep(self.delay)
        return super().decide(state, question)


class DelayedDesigner:
    """Waits, then fails, so the design ends as the reference template after its attempts."""

    def __init__(self, delay: float):
        self.delay = delay

    def draft(self, state, constraints, problems):
        time.sleep(self.delay)
        raise TimeoutError("simulated model")


def mock_trace(delay: float, design_delay: float = 0.0) -> list[dict[str, Any]]:
    """Answers every card with its first open option, preparing cards the way the screen does."""
    deps = JourneyDeps(
        advisor=DelayedAdvisor(delay),
        decider=DelayedDecider(delay),
        designer=DelayedDesigner(design_delay) if design_delay else None,
    )
    saver = InMemorySaver()
    service = JourneyService(load_registry(), saver, deps)
    view = service.start(ProjectSpec(**SPEC))
    for _ in range(MAX_STEPS):
        prompt = view.prompt
        if prompt is None or prompt["type"] == "done":
            break
        if prompt["type"] == "clarify":
            action = {"action": "clarify", "answers": {}}
        elif prompt["type"] == "fork":
            action = {"action": "plan_deploy"}
        elif prompt["type"] == "designing":
            action = {"action": "design"}
        elif prompt["card"].get("preparing"):
            action = {"action": "prepare"}
        else:
            option = next(v for v in prompt["card"]["options"] if not v["blocked_reason"])
            action = {"action": "select", "option_id": option["option"]["id"]}
        view = service.act(view.journey_id, view.revision, ACTION.validate_python(action))
    return saver.get_tuple(journey_config(view.journey_id)).checkpoint["channel_values"]["trace"]


def stored_trace(database_url: str, journey_id: UUID) -> list[dict[str, Any]]:
    """Reads only: no table setup and no graph run."""
    with connect(database_url, autocommit=True, row_factory=dict_row) as conn:
        checkpoint = PostgresSaver(conn).get_tuple(journey_config(journey_id))
    if checkpoint is None:
        raise SystemExit(f"journey {journey_id} not found")
    return checkpoint.checkpoint["channel_values"].get("trace", [])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--mock", action="store_true", help="run one journey with mock models")
    parser.add_argument(
        "--model-delay", type=float, default=0.0, help="simulated seconds per model call"
    )
    parser.add_argument(
        "--design-delay", type=float, default=0.0, help="simulated seconds per design call"
    )
    parser.add_argument("--database-url")
    parser.add_argument("--journey-id", type=UUID)
    args = parser.parse_args()
    if args.mock:
        trace = mock_trace(args.model_delay, args.design_delay)
    elif args.database_url and args.journey_id:
        trace = stored_trace(args.database_url, args.journey_id)
    else:
        parser.error("give --mock, or --database-url with --journey-id")
    waits = card_waits(trace)
    report = {"summary": summary(waits), "design": design_waits(trace), "cards": waits}
    print(json.dumps(report, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
