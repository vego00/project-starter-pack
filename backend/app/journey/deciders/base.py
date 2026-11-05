"""Decider: narrow judgement behind one interface (Jev / LLM / Mock)."""

import logging
from typing import TYPE_CHECKING, Protocol

from pydantic import BaseModel, ConfigDict, Field

if TYPE_CHECKING:
    from app.journey.state import JourneyState

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.7  # Initial value from the design doc; to be calibrated by EXP-002.


class DeciderQuestion(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    text: str
    choices: tuple[str, ...] = Field(min_length=1)
    criteria: dict[str, str] = Field(default_factory=dict)  # choice -> what it means
    default: str | None = None


class DeciderResult(BaseModel):
    answer: str
    confidence: float = Field(ge=0, le=1)
    model_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class Decider(Protocol):
    name: str

    def decide(self, state: "JourneyState", question: DeciderQuestion) -> DeciderResult: ...


class Judgement(BaseModel):
    """`answer` is None when the result is unusable, so callers take the safe path."""

    answer: str | None
    confidence: float | None = None
    decider: str
    model_id: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None

    def trace(self) -> dict[str, object]:
        return self.model_dump(exclude={"answer"})


def judge(decider: Decider, state: "JourneyState", question: DeciderQuestion) -> Judgement:
    """Checks format and meaning, and turns failures into "no answer" instead of crashing."""
    try:
        result = decider.decide(state, question)
    except Exception:  # noqa: BLE001 - decider boundary; question text may hold user input
        logger.error("Decider failed decider=%s question_id=%s", decider.name, question.id)
        return Judgement(answer=None, decider=decider.name)
    usable = result.answer in question.choices and result.confidence >= CONFIDENCE_THRESHOLD
    return Judgement(
        answer=result.answer if usable else None,
        confidence=result.confidence,
        decider=decider.name,
        model_id=result.model_id,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
    )
