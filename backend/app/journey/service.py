"""Runs journeys for the API: one graph, per-journey ordering, and a view for clients."""

from threading import Lock
from typing import Any, Literal
from uuid import UUID, uuid4
from weakref import WeakValueDictionary

from langgraph.types import Checkpointer, StateSnapshot
from pydantic import BaseModel

from app.journey.blueprint import Blueprint, BlueprintExample, blueprint_examples, build_blueprint
from app.journey.composers.summary import ARTIFACT_KEY
from app.journey.design import DesignState, ServiceDesign
from app.journey.design_constraints import derive_design_constraints
from app.journey.design_edit import (
    DesignEdit,
    DesignEditError,
    apply_design_edit,
    compose_renames,
)
from app.journey.graph import build_graph, journey_config, journey_input
from app.journey.modules import ModulePlan, build_module_plan
from app.journey.nodes import resume_command
from app.journey.package import build_package, package_zip
from app.journey.services import JourneyDeps
from app.journey.state import (
    ClarifyAction,
    Decision,
    GcbAction,
    JourneyAction,
    JourneyState,
    KeepAction,
    ProjectSpec,
    ReopenAction,
    ReviseAction,
)
from app.registry.loader import Registry
from app.registry.modules import default_module_rules

NO_MODEL_NOTICE = (
    "모델 미연결 상태입니다. 추천은 카드의 기본값이며 내 프로젝트를 분석한 결과가 아닙니다."
)
MOCK_RECOMMENDATION_NOTICE = (
    "선택지 설명은 AI가 쓰지만, 추천은 아직 카드의 기본값이며 내 프로젝트를 분석한 결과가 아닙니다."
)


class JourneyError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message


class CardStatus(BaseModel):
    card_id: str
    layer: str
    stage: int
    title: str
    question: str
    state: Literal["decided", "implied", "deferred", "current", "pending", "skipped"]
    needs_review: bool = False
    editing: bool = False
    option_id: str | None = None
    option_name: str | None = None
    by: Literal["user", "recommended", "implied"] | None = None
    rationale: str = ""
    # How sure the decider was that a skipped card is not needed.
    skip_confidence: float | None = None


class DesignNodeView(BaseModel):
    id: str
    kind: str
    responsibility: str


class DesignView(BaseModel):
    status: str
    source: str
    error: str | None
    nodes: list[DesignNodeView]
    first_task: str
    first_task_check: str
    unknowns: list[str]
    warnings: list[str]
    files: list[str]


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
    design: DesignView | None = None
    blueprint: Blueprint
    modules: list[ModulePlan] = []
    # Finished journeys made before the end wait existed cannot change a decision.
    can_reopen: bool = False


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
    if prompt_type == "done":
        return isinstance(action, ReopenAction | ReviseAction | KeepAction)
    if prompt_type == "clarify":
        return isinstance(action, ClarifyAction)
    if prompt_type == "gcb":
        return isinstance(action, GcbAction)
    if prompt_type == "issues":
        return isinstance(action, ReopenAction)
    return not isinstance(action, ClarifyAction | GcbAction)


class JourneyService:
    def __init__(
        self, registry: Registry, checkpointer: Checkpointer, deps: JourneyDeps | None = None
    ):
        self._registry = registry
        self._module_rules = default_module_rules()
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
            finished = prompt is None or prompt["type"] == "done"
            if finished and not (
                prompt is not None and isinstance(action, ReopenAction | ReviseAction | KeepAction)
            ):
                raise JourneyError(409, "journey_finished", "이미 끝난 여정이에요.")
            if not _allowed(prompt["type"], action):
                raise JourneyError(
                    409, "action_not_allowed", "지금 단계에서 할 수 없는 동작이에요."
                )
            if prompt["type"] == "done" and isinstance(action, ReopenAction | ReviseAction):
                self._check_reopen(JourneyState.model_validate(snapshot.values), action)
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

    def design(self, journey_id: UUID) -> ServiceDesign:
        with self._lock(journey_id):
            state = JourneyState.model_validate(self._snapshot(journey_id).values)
        if state.design.current is None:
            raise JourneyError(409, "design_unavailable", "결정을 모두 마치면 볼 수 있어요.")
        return state.design.current

    def save_design(self, journey_id: UUID, edit: DesignEdit) -> ServiceDesign:
        """Saves graph edits as a new revision; the download then follows the edited design."""
        with self._lock(journey_id):
            snapshot = self._snapshot(journey_id)
            state = JourneyState.model_validate(snapshot.values)
            current = state.design.current
            if current is None:
                raise JourneyError(409, "design_unavailable", "결정을 모두 마치면 고칠 수 있어요.")
            prompt = _pending_prompt(snapshot)
            if prompt is None or prompt["type"] != "done":
                raise JourneyError(409, "design_not_editable", "지금은 설계를 고칠 수 없어요.")
            if edit.design_revision != current.design_revision:
                raise JourneyError(
                    409, "stale_design", "설계가 그새 바뀌었어요. 다시 불러온 뒤 고쳐 주세요."
                )
            constraints = derive_design_constraints(state, self._registry)
            try:
                saved = apply_design_edit(current, edit, constraints)
            except DesignEditError as exc:
                raise JourneyError(422, "design_has_errors", " / ".join(exc.problems)) from None
            history = state.design.confirmed_history
            status = state.design.status
            if status == "confirmed":
                history, status = [*history, current], "review_required"
            design = DesignState(
                status=status,
                current=saved,
                confirmed_history=history,
                error=state.design.error,
                generated=state.design.generated or current,
                human_renames=compose_renames(state.design.human_renames, edit.renames),
            )
            self._graph.update_state(
                journey_config(journey_id),
                {"design": design.model_dump(mode="json")},
                as_node="designer",
            )
            self._snapshot(journey_id)
            return saved

    def blueprint_examples(self) -> list[BlueprintExample]:
        return blueprint_examples(self._registry)

    def package(self, journey_id: UUID) -> bytes:
        with self._lock(journey_id):
            state = JourneyState.model_validate(self._snapshot(journey_id).values)
        if state.design.current is None:
            raise JourneyError(409, "package_unavailable", "결정을 모두 마치면 받을 수 있어요.")
        files = build_package(state.design.current, self._registry, state.project_spec.idea)
        return package_zip(files)

    def _design_view(self, state: JourneyState) -> DesignView | None:
        design: ServiceDesign | None = state.design.current
        if design is None:
            return None
        files = build_package(design, self._registry, state.project_spec.idea)
        issues = [i.message for i in design.validation or [] if i.severity == "warning"]
        return DesignView(
            status=state.design.status,
            source=design.provenance.source,
            error=state.design.error,
            nodes=[
                DesignNodeView(id=node.id, kind=node.kind, responsibility=node.responsibility)
                for node in design.nodes
            ],
            first_task=design.tasks[0].title,
            first_task_check=design.tasks[0].verify_by,
            unknowns=[unknown.text for unknown in design.unknowns],
            warnings=[*design.warnings, *issues],
            files=sorted(files),
        )

    def _check_reopen(self, state: JourneyState, action: ReopenAction | ReviseAction) -> None:
        """Rejects before the graph runs, so a finished journey never shows a refusal as a step."""
        if action.card_id in state.skipped:
            return
        if action.card_id in state.implied:
            raise JourneyError(
                409,
                "reopen_rejected",
                "자동으로 정해진 결정이에요. 이 결정을 만든 앞선 선택을 바꿔 주세요.",
            )
        if action.card_id not in state.decisions:
            raise JourneyError(409, "reopen_rejected", "정하지 않은 카드는 다시 고를 수 없어요.")

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
        skipped = state.skipped
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
            elif card.card_id in skipped:
                kind = "skipped"
            else:
                kind = "pending"
            statuses.append(
                CardStatus(
                    card_id=card.card_id,
                    layer=card.layer,
                    stage=card.stage,
                    title=card.title,
                    question=card.question,
                    state=kind,
                    needs_review=card.card_id in state.needs_review,
                    editing=card.card_id == state.editing_card,
                    option_id=decision.option_id if decision else None,
                    option_name=option.name if option else None,
                    by=decision.by if decision else None,
                    rationale=decision.rationale if decision else "",
                    skip_confidence=(
                        state.skipped_cards[card.card_id].confidence if kind == "skipped" else None
                    ),
                )
            )
        return statuses

    def _notice(self) -> str | None:
        if not self._deps.recommendations_are_mock:
            return None
        return NO_MODEL_NOTICE if self._deps.explanations_are_mock else MOCK_RECOMMENDATION_NOTICE

    def _view(self, journey_id: UUID, snapshot: StateSnapshot) -> JourneyView:
        state = JourneyState.model_validate(snapshot.values)
        prompt = _pending_prompt(snapshot)
        waiting_at_end = prompt is not None and prompt["type"] == "done"
        status = state.status
        if prompt is not None and prompt["type"] in ("gcb", "clarify", "decision"):
            # A reopened card is asked again after the reviewer last said "completed".
            status = "in_progress"
        return JourneyView(
            journey_id=journey_id,
            revision=len(state.trace),
            status=status,
            idea=state.project_spec.idea,
            prompt=None if waiting_at_end else prompt,
            cards=self._card_statuses(state),
            warnings=[c.message for c in state.conflicts if c.severity == "warning"],
            notice=self._notice(),
            design=self._design_view(state),
            blueprint=build_blueprint(state, self._registry),
            modules=build_module_plan(
                self._registry,
                self._module_rules,
                {card_id: d.option_id for card_id, d in state.all_decisions.items()},
            ),
            can_reopen=waiting_at_end,
        )
