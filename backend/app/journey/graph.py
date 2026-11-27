"""Decision Journey graph. Flow is fixed here; no model picks the next node."""

from functools import wraps
from time import perf_counter
from typing import Any
from uuid import UUID

from langgraph.graph import START, StateGraph
from langgraph.types import Checkpointer
from pydantic import BaseModel

from app.journey.controller import deploy_planned, split_at_fork
from app.journey.nodes import Node, build_nodes
from app.journey.services import JourneyDeps
from app.journey.state import JourneyState, NodeEvent, ProjectSpec
from app.registry.loader import Registry

RECURSION_LIMIT = 50  # Per run between two interrupts; a normal run takes far fewer steps.
PREPARERS = ("advisor", "recommender", "retriever")

# Reopening a skipped card puts it back, so every gate may also write `skipped_cards`.
GATE_WRITES = {
    "decisions",
    "skipped_cards",
    "gate_outcome",
    "gate_error",
    "focus_card",
    "previous_choices",
    "needs_review",
    "editing_card",
}
NODE_WRITES: dict[str, set[str]] = {
    "gcb_drafter": {"gcb_draft", "start_fields", "start_chat"},
    "gcb_gate": {"gcb_answer", "clarifications", "clarify_rounds", "gate_outcome", "gate_error"},
    "intake": {"project_spec"},
    "clarify_gate": {"clarify_passed"},
    "clarify_question": {"clarifications", "clarify_rounds"},
    "card_selector": {"skipped_cards"},
    "constraint_engine": {"implied", "pending_cards", "conflicts", "blocked_options"},
    # Fills blank info the chosen card reads with defaults (ADR-024).
    "controller": {"current_card_id", "project_spec", "start_fields"},
    "advisor": {"advice"},
    "recommender": {"recommendation"},
    "retriever": {"evidence"},
    "present": {"current_card", "card_briefs"},
    # A `signal` action changes the card's info and drops its saved brief to prepare it again.
    "decision_gate": GATE_WRITES
    | {
        "deferred_cards",
        "pending_question",
        "project_spec",
        "start_fields",
        "card_briefs",
        "info_changed",
    },
    "qa": {"qa_history"},
    "reviewer": {"review_issues", "status"},
    "composer": {"artifacts"},
    "design_gate": {"gate_outcome", "gate_error"},
    "designer": {"design"},
    # Build preparation answers (ADR-026 ③). `done_gate` only sends the journey back here.
    "build_gate": GATE_WRITES | {"build_answers", "plan_scope"},
    "issue_gate": GATE_WRITES,
    "fork_gate": {"plan_scope", "focus_card", "editing_card", "gate_outcome", "gate_error"},
    "done_gate": GATE_WRITES | {"plan_scope"},
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


def _entry(state: JourneyState) -> str:
    # A caller that already supplies a goal has done this step.
    return "intake" if state.project_spec.goal else "gcb_drafter"


def _after_gcb(state: JourneyState) -> str:
    return "gcb_gate" if state.gate_outcome == "invalid" else "intake"


def _after_clarify(state: JourneyState) -> str:
    return "card_selector" if state.clarify_passed else "clarify_question"


def _after_engine_for(registry: Registry):
    def stage_of(card_id: str) -> int | None:
        return registry.card(card_id).stage if card_id in registry.card_ids else None

    def route(state: JourneyState) -> str:
        early, late = split_at_fork(state.pending_cards, lambda c: registry.card(c).stage)
        if early or state.editing_card:
            return "controller"
        if late and state.plan_scope != "agent":
            planned = deploy_planned(state.plan_scope, state.decisions, stage_of)
            return "controller" if planned else "fork_gate"
        # Nothing changed, so a finished design is not generated again.
        return "build_gate" if state.gate_outcome == "unchanged" else "reviewer"

    return route


def _after_decision(state: JourneyState) -> str | list[str]:
    if state.gate_outcome == "prepare":
        # Nothing the card reads changed, so the engine and controller are not run again.
        return list(PREPARERS)
    return {"ask": "qa", "invalid": "decision_gate", "keep": "decision_gate"}.get(
        state.gate_outcome, "constraint_engine"
    )


def _after_review(state: JourneyState) -> str:
    return "issue_gate" if state.status == "needs_fix" else "composer"


def _after_issue(state: JourneyState) -> str:
    return "issue_gate" if state.gate_outcome == "invalid" else "constraint_engine"


def _after_fork(state: JourneyState) -> str:
    return "fork_gate" if state.gate_outcome == "invalid" else "constraint_engine"


def _after_design_gate(state: JourneyState) -> str:
    return "design_gate" if state.gate_outcome == "invalid" else "designer"


def _after_build(state: JourneyState) -> str:
    if state.gate_outcome == "finish":
        return "done_gate"
    # An answer or a kept decision changes no card, so the design is not generated again.
    return "build_gate" if state.gate_outcome in ("invalid", "keep") else "constraint_engine"


def _after_done(state: JourneyState) -> str:
    if state.gate_outcome == "build":
        return "build_gate"
    # Keeping a decision changes nothing, so the design is not generated again.
    return "done_gate" if state.gate_outcome in ("invalid", "keep") else "constraint_engine"


def build_graph(registry: Registry, *, checkpointer: Checkpointer, deps: JourneyDeps | None = None):
    nodes = build_nodes(registry, deps or JourneyDeps())
    graph = StateGraph(JourneyState)
    for name, node in nodes.items():
        graph.add_node(name, _guarded(name, node))

    graph.add_conditional_edges(START, _entry, ["gcb_drafter", "intake"])
    graph.add_edge("gcb_drafter", "gcb_gate")
    graph.add_conditional_edges("gcb_gate", _after_gcb, ["gcb_gate", "intake"])
    graph.add_edge("intake", "clarify_gate")
    graph.add_conditional_edges(
        "clarify_gate", _after_clarify, ["clarify_question", "card_selector"]
    )
    graph.add_edge("clarify_question", "intake")
    graph.add_edge("card_selector", "constraint_engine")
    graph.add_conditional_edges(
        "constraint_engine",
        _after_engine_for(registry),
        ["controller", "fork_gate", "reviewer", "build_gate"],
    )
    graph.add_conditional_edges("fork_gate", _after_fork, ["fork_gate", "constraint_engine"])
    # A card without a usable brief is shown with its options first; `prepare` asks the models.
    graph.add_edge("controller", "present")
    graph.add_edge(["advisor", "recommender", "retriever"], "present")
    graph.add_edge("present", "decision_gate")
    graph.add_conditional_edges(
        "decision_gate", _after_decision, ["qa", "decision_gate", "constraint_engine", *PREPARERS]
    )
    graph.add_edge("qa", "decision_gate")
    graph.add_conditional_edges("reviewer", _after_review, ["issue_gate", "composer"])
    # The answer that ends the decisions comes back before the design; `design` makes it.
    graph.add_edge("composer", "design_gate")
    graph.add_conditional_edges("design_gate", _after_design_gate, ["design_gate", "designer"])
    # A finished journey waits here, so a decision can still change and the design follow it.
    graph.add_edge("designer", "build_gate")
    graph.add_conditional_edges(
        "build_gate", _after_build, ["build_gate", "done_gate", "constraint_engine"]
    )
    graph.add_conditional_edges(
        "done_gate", _after_done, ["done_gate", "build_gate", "constraint_engine"]
    )
    graph.add_conditional_edges("issue_gate", _after_issue, ["issue_gate", "constraint_engine"])
    return graph.compile(checkpointer=checkpointer)


def journey_config(journey_id: UUID) -> dict[str, Any]:
    return {"configurable": {"thread_id": str(journey_id)}, "recursion_limit": RECURSION_LIMIT}


def journey_input(journey_id: UUID, spec: ProjectSpec) -> dict[str, Any]:
    return {"journey_id": str(journey_id), "project_spec": spec.model_dump(mode="json")}
