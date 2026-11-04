"""Ports for the model-backed parts, with mock and real implementations."""

import logging
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from app.config import Settings
from app.journey.deciders.base import Decider
from app.journey.deciders.jev import JevDecider
from app.journey.deciders.mock import MockDecider
from app.journey.llm import GeminiLLM, StructuredLLM
from app.journey.prompts import (
    ADVISOR_SYSTEM,
    ADVISOR_VERSION,
    QA_SYSTEM,
    QA_VERSION,
    advisor_user,
    qa_user,
)
from app.journey.state import MAX_LLM_CALLS_PER_JOURNEY, Advice, Evidence, JourneyState
from app.registry.loader import Registry
from app.registry.schema import DecisionCard

logger = logging.getLogger(__name__)

MAX_NOTE_CHARS = 400
MAX_ANSWER_CHARS = 1500
QA_UNAVAILABLE = (
    "지금은 답변을 만들지 못했어요. 선택지의 장단점을 참고하거나 잠시 후 다시 질문해 주세요."
)


class Answer(BaseModel):
    text: str
    answered_by: str
    model_id: str | None = None
    prompt_version: str | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None


class Advisor(Protocol):
    def advise(self, state: JourneyState, card: DecisionCard) -> Advice: ...


class Retriever(Protocol):
    def retrieve(self, state: JourneyState, card: DecisionCard) -> list[Evidence]: ...


class Responder(Protocol):
    def answer(self, state: JourneyState, card: DecisionCard, question: str) -> Answer: ...


def llm_calls_used(state: JourneyState) -> int:
    return sum(event.node in ("advisor", "qa") and bool(event.model_id) for event in state.trace)


def _card_advice(card: DecisionCard, source: str) -> Advice:
    return Advice(source=source, notes={option.id: option.summary for option in card.options})


class MockAdvisor:
    """Repeats the card's own text; it does not analyse the project."""

    def advise(self, state: JourneyState, card: DecisionCard) -> Advice:
        return _card_advice(card, "mock")


class OptionNote(BaseModel):
    option_id: str
    note: str


class AdvisorOutput(BaseModel):
    notes: list[OptionNote]


class LLMAdvisor:
    """Falls back to the card's own text: a model failure must not block the decision."""

    def __init__(self, llm: StructuredLLM, registry: Registry):
        self._llm = llm
        self._registry = registry

    def advise(self, state: JourneyState, card: DecisionCard) -> Advice:
        if llm_calls_used(state) >= MAX_LLM_CALLS_PER_JOURNEY:
            logger.warning("LLM budget reached journey_id=%s", state.journey_id)
            return _card_advice(card, "card_text")
        try:
            result = self._llm.generate(
                system=ADVISOR_SYSTEM,
                user=advisor_user(state, card, self._registry),
                schema=AdvisorOutput,
            )
            notes = _checked_notes(result.output, card)
        except Exception as exc:  # noqa: BLE001 - model boundary; the prompt holds user text
            logger.error("Advisor failed card_id=%s type=%s", card.card_id, type(exc).__name__)
            return _card_advice(card, "card_text")
        return Advice(
            source="llm",
            notes=notes,
            model_id=result.model_id,
            prompt_version=ADVISOR_VERSION,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )


def _checked_notes(output: AdvisorOutput, card: DecisionCard) -> dict[str, str]:
    """A valid shape is not enough: every option must be covered, once, within the limit."""
    notes = {item.option_id: item.note.strip() for item in output.notes}
    expected = {option.id for option in card.options}
    if len(output.notes) != len(expected) or set(notes) != expected:
        raise ValueError("advisor output does not cover the card's options")
    if not all(0 < len(note) <= MAX_NOTE_CHARS for note in notes.values()):
        raise ValueError("advisor note is empty or too long")
    return notes


class EmptyRetriever:
    """No lecture corpus yet. An empty result is shown as "no evidence", never invented."""

    def retrieve(self, state: JourneyState, card: DecisionCard) -> list[Evidence]:
        return []


class MockResponder:
    def answer(self, state: JourneyState, card: DecisionCard, question: str) -> Answer:
        return Answer(
            text="모델 미연결 상태의 고정 응답입니다. 선택지의 장단점을 참고해 주세요.",
            answered_by="mock",
        )


class QAOutput(BaseModel):
    answer: str


class LLMResponder:
    def __init__(self, llm: StructuredLLM, registry: Registry):
        self._llm = llm
        self._registry = registry

    def answer(self, state: JourneyState, card: DecisionCard, question: str) -> Answer:
        unavailable = Answer(text=QA_UNAVAILABLE, answered_by="unavailable")
        if llm_calls_used(state) >= MAX_LLM_CALLS_PER_JOURNEY:
            return unavailable
        try:
            result = self._llm.generate(
                system=QA_SYSTEM,
                user=qa_user(state, card, self._registry, question),
                schema=QAOutput,
            )
            text = result.output.answer.strip()
            if not 0 < len(text) <= MAX_ANSWER_CHARS:
                raise ValueError("answer is empty or too long")
        except Exception as exc:  # noqa: BLE001 - model boundary; the prompt holds user text
            logger.error("Q&A failed card_id=%s type=%s", card.card_id, type(exc).__name__)
            return unavailable
        return Answer(
            text=text,
            answered_by="llm",
            model_id=result.model_id,
            prompt_version=QA_VERSION,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        )


@dataclass(frozen=True)
class JourneyDeps:
    decider: Decider = field(default_factory=MockDecider)
    advisor: Advisor = field(default_factory=MockAdvisor)
    retriever: Retriever = field(default_factory=EmptyRetriever)
    responder: Responder = field(default_factory=MockResponder)

    @property
    def recommendations_are_mock(self) -> bool:
        return self.decider.name == "mock"


def build_deps(settings: Settings, registry: Registry) -> JourneyDeps:
    decider: Decider = MockDecider()
    if settings.decider == "jev":
        decider = JevDecider(
            settings.ai_gateway_api_key.get_secret_value(), settings.jev_model, registry
        )
    if settings.provider != "gemini":
        return JourneyDeps(decider=decider)
    llm = GeminiLLM(settings.gemini_api_key.get_secret_value(), settings.gemini_model)
    return JourneyDeps(
        decider=decider,
        advisor=LLMAdvisor(llm, registry),
        responder=LLMResponder(llm, registry),
    )
