"""Runs journeys for the API: one graph, per-journey ordering, and a view for clients."""

from threading import Lock
from typing import Any, Literal
from uuid import UUID, uuid4
from weakref import WeakValueDictionary

from langgraph.types import Checkpointer, StateSnapshot
from pydantic import BaseModel

from app.journey.composers.summary import ARTIFACT_KEY
from app.journey.graph import build_graph, journey_config, journey_input
from app.journey.nodes import resume_command
from app.journey.services import JourneyDeps
from app.journey.state import (
    ClarifyAction,
    Decision,
    JourneyAction,
    JourneyState,
    ProjectSpec,
    ReopenAction,
)
from app.registry.loader import Registry

MOCK_NOTICE = (
    "모델 미연결 상태입니다. 추천은 카드의 기본값이며 내 프로젝트를 분석한 결과가 아닙니다."
)


class JourneyError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


class CardStatus(BaseModel):
    card_id: str
    layer: str
    question: str
    state: Literal["decided", "implied", "deferred", "current", "pending"]
    option_id: str | None = None
    option_name: str | None = None
    by: Literal["user", "recommended", "implied"] | None = None
    rationale: str = ""


class JourneyView(BaseModel):
    journey_id: UUID
    # Echoed back on each action, so a double click or stale tab cannot answer the wrong card.
    revision: int
    status: Literal["in_progress", "needs_fix", "completed"]
    idea: str
    prompt: dict[str, Any] | None
    cards: list[CardStatus]
    warnings: list[str]
    notice: str | None


def _pending_prompt(snapshot: StateSnapshot) -> dict[str, Any] | None:
    for task in snapshot.tasks:
        if task.interrupts:
            return task.interrupts[0].value
    return None


def _resume_payload(action: JourneyAction) -> Any:
    if isinstance(action, ClarifyAction):
        return action.answers
    return action.model_dump(mode="json")


def _allowed(prompt_type: str, action: JourneyAction) -> bool:
    if prompt_type == "clarify":
        return isinstance(action, ClarifyAction)
    if prompt_type == "issues":
        return isinstance(action, ReopenAction)
    return not isinstance(action, ClarifyAction)


class JourneyService:
    def __init__(
        self, registry: Registry, checkpointer: Checkpointer, deps: JourneyDeps | None = None
    ):
        self._registry = registry
        self._deps = deps or JourneyDeps()
        self._graph = build_graph(registry, checkpointer=checkpointer, deps=self._deps)
        # Orders actions within this process. More than one backend instance needs a DB lock.
        self._locks: WeakValueDictionary[UUID, Any] = WeakValueDictionary()
        self._locks_guard = Lock()

    def start(self, spec: ProjectSpec) -> JourneyView:
        journey_id = uuid4()
        with self._lock(journey_id):
            self._graph.invoke(journey_input(journey_id, spec), journey_config(journey_id))
            return self._view(journey_id, self._snapshot(journey_id))

    def get(self, journey_id: UUID) -> JourneyView:
        with self._lock(journey_id):
            return self._view(journey_id, self._snapshot(journey_id))

    def act(self, journey_id: UUID, revision: int, action: JourneyAction) -> JourneyView:
        with self._lock(journey_id):
            snapshot = self._snapshot(journey_id)
            if len(snapshot.values.get("trace", [])) != revision:
                raise JourneyError(
                    409, "stale_revision", "화면이 최신 상태가 아니에요. 최신 내용을 불러왔어요."
                )
            prompt = _pending_prompt(snapshot)
            if prompt is None:
                raise JourneyError(409, "journey_finished", "이미 끝난 여정이에요.")
            if not _allowed(prompt["type"], action):
                raise JourneyError(
                    409, "action_not_allowed", "지금 단계에서 할 수 없는 동작이에요."
                )
            config = journey_config(journey_id)
            self._graph.invoke(resume_command(_resume_payload(action)), config)
            return self._view(journey_id, self._snapshot(journey_id))

    def summary(self, journey_id: UUID) -> str:
        with self._lock(journey_id):
            values = self._snapshot(journey_id).values
        document = values.get("artifacts", {}).get(ARTIFACT_KEY)
        if document is None:
            raise JourneyError(409, "summary_unavailable", "결정을 모두 마치면 받을 수 있어요.")
        return document

    def _lock(self, journey_id: UUID) -> Any:
        with self._locks_guard:
            lock = self._locks.get(journey_id)
            if lock is None:
                lock = Lock()
                self._locks[journey_id] = lock
            return lock

    def _snapshot(self, journey_id: UUID) -> StateSnapshot:
        config = journey_config(journey_id)
        snapshot = self._graph.get_state(config)
        if not snapshot.values:
            raise JourneyError(404, "journey_not_found", "여정을 찾을 수 없어요.")
        if snapshot.next and _pending_prompt(snapshot) is None:
            # A run failed between two interrupts: continue from the last saved step.
            self._graph.invoke(None, config)
            snapshot = self._graph.get_state(config)
        return snapshot

    def _card_statuses(self, state: JourneyState) -> list[CardStatus]:
        decided: dict[str, Decision] = state.all_decisions
        statuses = []
        for card in self._registry.cards:
            decision = decided.get(card.card_id)
            option = card.option(decision.option_id) if decision else None
            if decision is not None:
                kind = "implied" if decision.by == "implied" else "decided"
            elif card.card_id == state.current_card_id:
                kind = "current"
            elif card.card_id in state.deferred_cards:
                kind = "deferred"
            else:
                kind = "pending"
            statuses.append(
                CardStatus(
                    card_id=card.card_id,
                    layer=card.layer,
                    question=card.question,
                    state=kind,
                    option_id=decision.option_id if decision else None,
                    option_name=option.name if option else None,
                    by=decision.by if decision else None,
                    rationale=decision.rationale if decision else "",
                )
            )
        return statuses

    def _view(self, journey_id: UUID, snapshot: StateSnapshot) -> JourneyView:
        state = JourneyState.model_validate(snapshot.values)
        return JourneyView(
            journey_id=journey_id,
            revision=len(state.trace),
            status=state.status,
            idea=state.project_spec.idea,
            prompt=_pending_prompt(snapshot),
            cards=self._card_statuses(state),
            warnings=[c.message for c in state.conflicts if c.severity == "warning"],
            notice=MOCK_NOTICE if self._deps.recommendations_are_mock else None,
        )
