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
    recommendation: Recommendation
    evidence: list[Evidence] = []
    advice_source: str
    # While changing a decision: later decisions that get marked for another look.
    to_review: list[str] = []
    learning_refs: list[str] = []
    div_refs: list[str] = []
    signals: list[CardSignal] = []


class CardBrief(BaseModel):
    """What the models said about a card, kept so reopening it costs no call."""

    advice: Advice
    recommendation: Recommendation
    evidence: list[Evidence] = []


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
    advice: Advice | None = None
    recommendation: Recommendation | None = None
    evidence: list[Evidence] = []
    current_card: CardPresentation | None = None
    card_briefs: dict[CardId, CardBrief] = {}
    gate_outcome: Literal["advance", "ask", "invalid", "keep", "unchanged"] | None = None
    gate_error: str | None = None
    pending_question: str | None = None
    qa_history: list[CardQA] = []
    review_issues: list[Conflict] = []
    status: Literal["in_progress", "needs_fix", "completed"] = "in_progress"
    artifacts: dict[str, str] = {}
    design: DesignState = DesignState()
    # The build order's conversation (ADR-022). Each change pushes the notes it replaced.
    module_notes: dict[str, ModuleNote] = {}
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

    @property
    def saved_brief(self) -> CardBrief | None:
        """Looking at a decision costs nothing, unless an earlier change made it out of date."""
        card_id = self.current_card_id
        if card_id != self.editing_card or card_id in self.needs_review:
            return None
        return self.card_briefs.get(card_id)

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
    | SignalAction,
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
    | ClarifyAction
    | GcbAction,
    Field(discriminator="action"),
]
GCB_ACTION = TypeAdapter(GcbAction)
GATE_ACTION = TypeAdapter(GateAction)
ISSUE_ACTION = TypeAdapter(ReopenAction)
DONE_ACTION = TypeAdapter(
    Annotated[ReopenAction | ReviseAction | KeepAction, Field(discriminator="action")]
)
