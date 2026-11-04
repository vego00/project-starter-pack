"""Journey contracts (Notion 02-1 §6). Checkpoints hold JSON only; see `nodes._jsonable`."""

import operator
from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from app.journey.constraints import Conflict
from app.registry.schema import CardOption

CardId = str
DeploymentTarget = Literal["local_demo", "small_group", "public_service"]
MAX_CLARIFY_ROUNDS = 2
MAX_QUESTIONS_PER_ROUND = 3
MAX_QUESTIONS_PER_CARD = 5
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
    team_size: int | None = Field(default=None, ge=1)
    duration_weeks: int | None = Field(default=None, ge=1)
    budget: str | None = Field(default=None, min_length=1, max_length=200)
    expected_users: int | None = Field(default=None, ge=0)
    weekly_hours: int | None = Field(default=None, ge=1)
    data_traits: list[Annotated[str, Field(max_length=200)]] | None = Field(
        default=None, max_length=20
    )
    deployment_target: DeploymentTarget | None = None
    has_gpu: bool | None = None

    def missing_signals(self) -> list[str]:
        return [name for name in CLARIFY_QUESTIONS if getattr(self, name) is None]


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
    implies: dict[CardId, str] = {}  # card_id -> option_id
    implied_messages: list[str] = []
    warnings: list[str] = []
    artifacts: list[str] = []


class CardPresentation(BaseModel):
    card_id: CardId
    version: int
    layer: str
    question: str
    options: list[OptionView]
    recommendation: Recommendation
    evidence: list[Evidence] = []
    advice_source: str
    learning_refs: list[str] = []
    div_refs: list[str] = []


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
    clarifications: list[QA] = []
    clarify_rounds: int = 0
    clarify_passed: bool = False
    # User-made decisions only. Implied ones are derived from these and owned by the engine.
    decisions: dict[CardId, Decision] = {}
    implied: dict[CardId, Decision] = {}
    pending_cards: list[CardId] = []
    deferred_cards: list[CardId] = []
    blocked_options: dict[CardId, dict[str, str]] = {}
    conflicts: list[Conflict] = []
    current_card_id: CardId | None = None
    advice: Advice | None = None
    recommendation: Recommendation | None = None
    evidence: list[Evidence] = []
    current_card: CardPresentation | None = None
    gate_outcome: Literal["advance", "ask", "invalid"] | None = None
    gate_error: str | None = None
    pending_question: str | None = None
    qa_history: list[CardQA] = []
    review_issues: list[Conflict] = []
    status: Literal["in_progress", "needs_fix", "completed"] = "in_progress"
    artifacts: dict[str, str] = {}
    trace: Annotated[list[NodeEvent], operator.add] = []

    @property
    def all_decisions(self) -> dict[CardId, Decision]:
        return {**self.decisions, **self.implied}


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


class ClarifyAction(_Action):
    action: Literal["clarify"]
    answers: dict[str, Any] = Field(max_length=len(CLARIFY_QUESTIONS))


GateAction = Annotated[
    SelectAction | AcceptRecommendationAction | DeferAction | AskAction | ReopenAction,
    Field(discriminator="action"),
]
JourneyAction = Annotated[
    SelectAction
    | AcceptRecommendationAction
    | DeferAction
    | AskAction
    | ReopenAction
    | ClarifyAction,
    Field(discriminator="action"),
]
GATE_ACTION = TypeAdapter(GateAction)
ISSUE_ACTION = TypeAdapter(ReopenAction)
