"""Journey contracts. Checkpoints hold JSON only; see `nodes._jsonable`."""

import operator
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.journey.constraints import Conflict
from app.journey.design import DesignState
from app.journey.modules import ModuleNote, ModuleTurn
from app.journey.start import StartSource, StartTurn, StartValue
from app.registry.schema import CardOption

CardId = str
RangeText = Annotated[str, Field(min_length=1, max_length=40)]
DeploymentTarget = Literal["local_demo", "small_group", "public_service"]
MAX_CLARIFY_ROUNDS = 2
MAX_QUESTIONS_PER_ROUND = 3
MAX_QUESTIONS_PER_CARD = 5
MAX_GCB_CHARS = 1000
MAX_LLM_CALLS_PER_JOURNEY = 40  # Provisional cost ceiling; recalibrate from real usage.

# Ordered by how many decisions the signal changes; only unanswered ones are asked.
CLARIFY_QUESTIONS: dict[str, str] = {
    "deployment_target": "어디까지 배포할 계획인가요? (로컬 데모 / 소수 사용자 / 공개 서비스)",
    "has_gpu": "모델을 직접 실행할 GPU 장비가 있나요?",
    "expected_users": "실제로 사용할 사람은 몇 명 정도인가요?",
    "budget": "모델 호출과 서버에 쓸 수 있는 예산은 어느 정도인가요?",
    "team_size": "함께 개발하는 인원은 몇 명인가요?",
    "duration_weeks": "개발 기간은 몇 주인가요?",
    "weekly_hours": "일주일에 개발에 쓸 수 있는 시간은 몇 시간인가요?",
    "data_traits": "다루는 데이터의 특징을 알려주세요. (문서 검색 필요, 개인정보 포함 등)",
}


class ProjectSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    idea: str = Field(min_length=10, max_length=3000)
    # GCB: the state to reach, what a judge must know, and what the result must satisfy.
    goal: str | None = Field(default=None, min_length=1, max_length=MAX_GCB_CHARS)
    context: str | None = Field(default=None, min_length=1, max_length=MAX_GCB_CHARS)
    boundary: str | None = Field(default=None, min_length=1, max_length=MAX_GCB_CHARS)
    # A range picked on the start screen ("10~100명") stays text; nothing invents a number for it.
    team_size: Annotated[int, Field(ge=1)] | RangeText | None = None
    duration_weeks: Annotated[int, Field(ge=1)] | RangeText | None = None
    budget: str | None = Field(default=None, min_length=1, max_length=200)
    expected_users: Annotated[int, Field(ge=0)] | RangeText | None = None
    weekly_hours: Annotated[int, Field(ge=1)] | RangeText | None = None
    data_traits: list[Annotated[str, Field(max_length=200)]] | None = Field(
        default=None, max_length=20
    )
    deployment_target: DeploymentTarget | None = None
    has_gpu: bool | None = None

    def missing_signals(self) -> list[str]:
        return [name for name in CLARIFY_QUESTIONS if getattr(self, name) is None]


class GcbDraft(BaseModel):
    """`source` tells the screen whether a model wrote this; "none" means an empty form."""

    goal: str = ""
    context: str = ""
    boundary: str = ""
    source: str = "none"
    model_id: str | None = None
    prompt_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class QA(BaseModel):
    field: str
    question: str
    answer: Any


class Decision(BaseModel):
    card_id: CardId
    card_version: int
    option_id: str
    by: Literal["user", "recommended", "implied"]
    rationale: str = ""
    at: datetime


class SkippedCard(BaseModel):
    """A card the decider judged not needed for this project, so it is not asked (ADR-018)."""

    confidence: float
    decider: str


class Recommendation(BaseModel):
    """`option_id=None` means "비교 필요": no recommendation is forced below the threshold."""

    status: Literal["recommended", "needs_comparison"]
    option_id: str | None = None
    confidence: float | None = None
    reason: str = ""
    decider: str


class Advice(BaseModel):
    """`source` tells the screen whether an LLM wrote this or the card's own text is shown."""

    source: str
    notes: dict[str, str] = {}  # option_id -> explanation
    model_id: str | None = None
    prompt_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class Evidence(BaseModel):
    """A pointer to a source, not its text. `kind` keeps notes from passing as lecture originals."""

    source_id: str
    title: str
    kind: str
    location: str
    why: str
    url: str | None = None


class OptionView(BaseModel):
    option: CardOption
    note: str = ""
    blocked_reason: str | None = None
    icon: str | None = None
    implies: dict[CardId, str] = {}  # card_id -> option_id
    implied_messages: list[str] = []
    warnings: list[str] = []
    # While changing a decision: answers elsewhere that stop fitting if this option is chosen.
    must_change: list[str] = []
    artifacts: list[str] = []


class SignalChoice(BaseModel):
    value: str
    label: str


class CardSignal(BaseModel):
    """Project info a card reads, shown above its options so it can be changed there (ADR-024).
    `source` is None for a value given to the journey directly rather than on the start screen."""

    name: str
    label: str
    kind: Literal["text", "choice", "multi"]
    choices: list[SignalChoice]
    free_text: bool
    value: str | list[str]
    display: str
    source: StartSource | None = None
    why: str | None = None


class CardPresentation(BaseModel):
    card_id: CardId
    version: int
    layer: str
    question: str
    options: list[OptionView]
    # None while preparing: the card shows its options before the models have answered.
    recommendation: Recommendation | None
    evidence: list[Evidence] = []
    advice_source: str
    preparing: bool = False
    # While changing a decision: later decisions that get marked for another look.
    to_review: list[str] = []
    learning_refs: list[str] = []
    div_refs: list[str] = []
    signals: list[CardSignal] = []


class BriefInputs(BaseModel):
    """What the models read when they wrote a brief (`prompts.project_context`), minus the
    card's own answer, which says nothing about how to answer it."""

    project: dict[str, Any]
    decided: dict[CardId, str]

    def still_hold(self, now: "BriefInputs") -> bool:
        """Nothing the brief saw has changed. Values that appeared since are not compared."""
        return all(now.project.get(k) == v for k, v in self.project.items()) and all(
            now.decided.get(k) == v for k, v in self.decided.items()
        )


class CardBrief(BaseModel):
    """What the models said about a card, kept so reopening it costs no call."""

    advice: Advice
    recommendation: Recommendation
    evidence: list[Evidence] = []
    # None on briefs saved before the inputs were kept.
    inputs: BriefInputs | None = None


class CardQA(BaseModel):
    card_id: CardId
    question: str
    answer: str
    answered_by: str


class NodeEvent(BaseModel):
    """Metadata only: user text must not reach the trace."""

    node: str
    latency_ms: float
    decider: str | None = None
    confidence: float | None = None
    model_id: str | None = None
    prompt_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class BuildAnswer(BaseModel):
    """One answer in build preparation. `inputs` is what the item showed when it was answered;
    when the item shows something else now, the answer is due for another look. Nothing stores
    that flag, so a new design or a changed card cannot leave a stale one behind."""

    model_config = ConfigDict(extra="forbid")

    value: str = Field(default="", max_length=2000)
    by: Literal["user", "recommended", "held"]
    at: datetime
    design_revision: int
    inputs: dict[str, str | None] = {}


class JourneyState(BaseModel):
    journey_id: UUID
    project_spec: ProjectSpec
    gcb_draft: GcbDraft | None = None
    gcb_answer: dict[str, str] = {}  # What the user confirmed; blanks are left out.
    clarifications: list[QA] = []
    clarify_rounds: int = 0
    clarify_passed: bool = False
    # User-made decisions only. Implied ones are derived from these and owned by the engine.
    decisions: dict[CardId, Decision] = {}
    implied: dict[CardId, Decision] = {}
    pending_cards: list[CardId] = []
    deferred_cards: list[CardId] = []
    # Set once after clarify. A rule on a decided card can still bring one back (`pending_cards`).
    skipped_cards: dict[CardId, SkippedCard] = {}
    blocked_options: dict[CardId, dict[str, str]] = {}
    conflicts: list[Conflict] = []
    current_card_id: CardId | None = None
    # The open card the user moved to, ahead of the normal order.
    focus_card: CardId | None = None
    # What a reopened card held, so choosing the same option again changes nothing downstream.
    previous_choices: dict[CardId, str] = {}
    # A decided card opened to be changed. Its decision stands until another option is chosen.
    editing_card: CardId | None = None
    # Decisions in later stages made before an earlier stage changed.
    needs_review: list[CardId] = []
    # Chosen at the fork after the agent stage (ADR-024): "agent" ends there, None is not asked yet.
    plan_scope: Literal["agent", "full"] | None = None
    advice: Advice | None = None
    recommendation: Recommendation | None = None
    evidence: list[Evidence] = []
    current_card: CardPresentation | None = None
    card_briefs: dict[CardId, CardBrief] = {}
    gate_outcome: (
        Literal["advance", "ask", "invalid", "keep", "unchanged", "prepare", "finish", "build"]
        | None
    ) = None
    gate_error: str | None = None
    pending_question: str | None = None
    qa_history: list[CardQA] = []
    review_issues: list[Conflict] = []
    status: Literal["in_progress", "needs_fix", "completed"] = "in_progress"
    artifacts: dict[str, str] = {}
    design: DesignState = DesignState()
    # The build order's conversation (ADR-022). Each change pushes the notes it replaced.
    module_notes: dict[str, ModuleNote] = {}
    # Build preparation answers (ADR-026 ③), kept across new designs. Empty for older journeys.
    build_answers: dict[str, BuildAnswer] = {}
    module_chat: list[ModuleTurn] = []
    module_undo: list[dict[str, ModuleNote]] = []
    module_revision: int = 0
    # The start screen's conversation and fields (ADR-023), kept until the journey starts.
    start_fields: dict[str, StartValue] = {}
    # Project info changed on the open card (ADR-024); leaving it "unchanged" still rebuilds.
    info_changed: bool = False
    start_chat: list[StartTurn] = []
    start_revision: int = 0
    trace: Annotated[list[NodeEvent], operator.add] = []

    def brief_inputs(self, card_id: CardId) -> BriefInputs:
        return BriefInputs(
            project=self.project_spec.model_dump(mode="json", exclude_none=True),
            decided={c: d.option_id for c, d in self.all_decisions.items() if c != card_id},
        )

    @property
    def saved_brief(self) -> CardBrief | None:
        """Opening a card again costs nothing, unless something its brief read has changed."""
        card_id = self.current_card_id
        brief = self.card_briefs.get(card_id)
        if brief is None:
            return None
        if brief.inputs is None:
            # Without the inputs, only a decision no earlier change touched is known to hold.
            editing = card_id == self.editing_card and card_id not in self.needs_review
            return brief if editing else None
        if brief.recommendation.option_id in self.blocked_options.get(card_id, {}):
            return None
        return brief if brief.inputs.still_hold(self.brief_inputs(card_id)) else None

    @property
    def all_decisions(self) -> dict[CardId, Decision]:
        return {**self.decisions, **self.implied}

    @property
    def skipped(self) -> set[CardId]:
        """Skipped cards that stay out: not brought back by a rule and not decided."""
        return set(self.skipped_cards) - set(self.pending_cards) - set(self.all_decisions)


class _Action(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class SelectAction(_Action):
    action: Literal["select"]
    option_id: str
    rationale: str = Field(default="", max_length=2000)


class AcceptRecommendationAction(_Action):
    action: Literal["accept_recommendation"]


class DeferAction(_Action):
    action: Literal["defer"]


class DesignAction(_Action):
    """Makes the service design once every decision is in; it is the journey's longest wait."""

    action: Literal["design"]


class PrepareAction(_Action):
    """Asks the models about a card that was shown with its options only."""

    action: Literal["prepare"]


class AskAction(_Action):
    action: Literal["ask"]
    question: str = Field(min_length=1, max_length=2000)


class ReopenAction(_Action):
    action: Literal["reopen"]
    card_id: CardId


class ReviseAction(_Action):
    action: Literal["revise"]
    card_id: CardId


class FocusAction(_Action):
    action: Literal["focus"]
    card_id: CardId


class KeepAction(_Action):
    action: Literal["keep"]
    card_id: CardId


class SignalAction(_Action):
    """Changes one piece of project info the current card reads; a multi-choice field sends
    its whole list in `values`."""

    action: Literal["signal"]
    field: str = Field(max_length=40)
    value: str = Field(default="", max_length=1000)
    values: list[Annotated[str, Field(max_length=200)]] = Field(default=[], max_length=20)


class EndHereAction(_Action):
    """Ends at the agent design; the system cards stay undecided (ADR-024)."""

    action: Literal["end_here"]


class PlanDeployAction(_Action):
    """Goes on to the system cards, from `card_id` when given."""

    action: Literal["plan_deploy"]
    card_id: CardId | None = None


BuildKey = Annotated[str, Field(min_length=1, max_length=120)]


class BuildAnswerAction(_Action):
    """A build preparation answer the user wrote, or one of the item's options."""

    action: Literal["build_answer"]
    key: BuildKey
    value: str = Field(min_length=1, max_length=2000)


class BuildAcceptAction(_Action):
    action: Literal["build_accept"]
    key: BuildKey


class BuildAcceptAllAction(_Action):
    """Every item with a recommendation and no answer yet, or one due for another look."""

    action: Literal["build_accept_all"]


class BuildHoldAction(_Action):
    """Leaves the item for the builder to ask; the bundle says so."""

    action: Literal["build_hold"]
    key: BuildKey


class BuildKeepAction(_Action):
    """Keeps an answer due for another look as it is."""

    action: Literal["build_keep"]
    key: BuildKey


class BuildFinishAction(_Action):
    action: Literal["build_finish"]


class BuildPrepAction(_Action):
    """From the finished journey back to build preparation."""

    action: Literal["build_prep"]


class GcbAction(_Action):
    action: Literal["gcb"]
    goal: str = Field(default="", max_length=MAX_GCB_CHARS)
    context: str = Field(default="", max_length=MAX_GCB_CHARS)
    boundary: str = Field(default="", max_length=MAX_GCB_CHARS)
    # Sent when the screen asked the clarifying questions together with these fields.
    answers: dict[str, Any] | None = Field(default=None, max_length=len(CLARIFY_QUESTIONS))


class ClarifyAction(_Action):
    action: Literal["clarify"]
    answers: dict[str, Any] = Field(max_length=len(CLARIFY_QUESTIONS))


GateAction = Annotated[
    SelectAction
    | AcceptRecommendationAction
    | DeferAction
    | AskAction
    | ReopenAction
    | ReviseAction
    | FocusAction
    | KeepAction
    | SignalAction
    | PrepareAction,
    Field(discriminator="action"),
]
JourneyAction = Annotated[
    SelectAction
    | AcceptRecommendationAction
    | DeferAction
    | AskAction
    | ReopenAction
    | ReviseAction
    | FocusAction
    | KeepAction
    | SignalAction
    | PrepareAction
    | DesignAction
    | EndHereAction
    | PlanDeployAction
    | ClarifyAction
    | GcbAction
    | BuildAnswerAction
    | BuildAcceptAction
    | BuildAcceptAllAction
    | BuildHoldAction
    | BuildKeepAction
    | BuildFinishAction
    | BuildPrepAction,
    Field(discriminator="action"),
]
BUILD_ANSWERS = (
    BuildAnswerAction,
    BuildAcceptAction,
    BuildAcceptAllAction,
    BuildHoldAction,
    BuildKeepAction,
)
GCB_ACTION = TypeAdapter(GcbAction)
GATE_ACTION = TypeAdapter(GateAction)
DESIGN_ACTION = TypeAdapter(DesignAction)
ISSUE_ACTION = TypeAdapter(ReopenAction)
FORK_ACTION = TypeAdapter(
    Annotated[EndHereAction | PlanDeployAction | ReviseAction, Field(discriminator="action")]
)
DONE_ACTION = TypeAdapter(
    Annotated[
        ReopenAction | ReviseAction | KeepAction | PlanDeployAction | BuildPrepAction,
        Field(discriminator="action"),
    ]
)
BUILD_ACTION = TypeAdapter(
    Annotated[
        BuildAnswerAction
        | BuildAcceptAction
        | BuildAcceptAllAction
        | BuildHoldAction
        | BuildKeepAction
        | BuildFinishAction
        | ReopenAction
        | ReviseAction
        | KeepAction
        | PlanDeployAction,
        Field(discriminator="action"),
    ]
)
