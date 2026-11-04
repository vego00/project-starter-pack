"""Decision Journey graph (Notion 02-1 §4). Flow is fixed here; no model picks the next node."""

from functools import wraps
from time import perf_counter
from typing import Any
from uuid import UUID

from langgraph.graph import END, START, StateGraph
from langgraph.types import Checkpointer
from pydantic import BaseModel

from app.journey.nodes import Node, build_nodes
from app.journey.services import JourneyDeps
from app.journey.state import JourneyState, NodeEvent, ProjectSpec
from app.registry.loader import Registry

RECURSION_LIMIT = 50  # Per run between two interrupts; a normal run takes far fewer steps.

GATE_WRITES = {"decisions", "gate_outcome", "gate_error"}
NODE_WRITES: dict[str, set[str]] = {
    "intake": {"project_spec"},
    "clarify_gate": {"clarify_passed"},
    "clarify_question": {"clarifications", "clarify_rounds"},
    "constraint_engine": {"implied", "pending_cards", "conflicts", "blocked_options"},
    "controller": {"current_card_id"},
    "advisor": {"advice"},
    "recommender": {"recommendation"},
    "retriever": {"evidence"},
    "present": {"current_card"},
    "decision_gate": GATE_WRITES | {"deferred_cards", "pending_question"},
    "qa": {"qa_history"},
    "reviewer": {"review_issues", "status"},
    "issue_gate": GATE_WRITES,
}


class OwnershipError(RuntimeError):
    pass


def _jsonable(value: Any) -> Any:
    """Keeps checkpoints as plain JSON so stored journeys do not depend on Python classes."""
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _guarded(name: str, node: Node) -> Node:
    """Rejects writes outside a node's fields (DiV P2) and records one trace event per run."""
    allowed = NODE_WRITES[name]

    @wraps(node)
    def run(state: JourneyState) -> dict[str, Any]:
        started = perf_counter()
        update = dict(node(state))
        meta = update.pop("_trace", {})
        if outside := set(update) - allowed:
            raise OwnershipError(f"{name} wrote fields it does not own: {sorted(outside)}")
        latency_ms = (perf_counter() - started) * 1000
        event = NodeEvent(node=name, latency_ms=latency_ms, **meta)
        return {**_jsonable(update), "trace": [event.model_dump(mode="json")]}

    return run


def _after_clarify(state: JourneyState) -> str:
    return "constraint_engine" if state.clarify_passed else "clarify_question"


def _after_engine(state: JourneyState) -> str:
    return "controller" if state.pending_cards else "reviewer"


def _after_decision(state: JourneyState) -> str:
    return {"ask": "qa", "invalid": "decision_gate"}.get(state.gate_outcome, "constraint_engine")


def _after_review(state: JourneyState) -> str:
    return "issue_gate" if state.status == "needs_fix" else END


def _after_issue(state: JourneyState) -> str:
    return "issue_gate" if state.gate_outcome == "invalid" else "constraint_engine"


def build_graph(registry: Registry, *, checkpointer: Checkpointer, deps: JourneyDeps | None = None):
    nodes = build_nodes(registry, deps or JourneyDeps())
    graph = StateGraph(JourneyState)
    for name, node in nodes.items():
        graph.add_node(name, _guarded(name, node))

    graph.add_edge(START, "intake")
    graph.add_edge("intake", "clarify_gate")
    graph.add_conditional_edges(
        "clarify_gate", _after_clarify, ["clarify_question", "constraint_engine"]
    )
    graph.add_edge("clarify_question", "intake")
    graph.add_conditional_edges("constraint_engine", _after_engine, ["controller", "reviewer"])
    for preparer in ("advisor", "recommender", "retriever"):
        graph.add_edge("controller", preparer)
    graph.add_edge(["advisor", "recommender", "retriever"], "present")
    graph.add_edge("present", "decision_gate")
    graph.add_conditional_edges(
        "decision_gate", _after_decision, ["qa", "decision_gate", "constraint_engine"]
    )
    graph.add_edge("qa", "decision_gate")
    graph.add_conditional_edges("reviewer", _after_review, ["issue_gate", END])
    graph.add_conditional_edges("issue_gate", _after_issue, ["issue_gate", "constraint_engine"])
    return graph.compile(checkpointer=checkpointer)


def journey_config(journey_id: UUID) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(journey_id)}, "recursion_limit": RECURSION_LIMIT}


def journey_input(journey_id: UUID, spec: ProjectSpec) -> dict[str, Any]:
    return {"journey_id": str(journey_id), "project_spec": spec.model_dump(mode="json")}
