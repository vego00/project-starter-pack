"""Ports for the model-backed parts. S2 ships mocks; LLM and RAG implementations arrive in S3."""

from dataclasses import dataclass, field
from typing import Protocol

from app.journey.deciders.base import Decider
from app.journey.deciders.mock import MockDecider
from app.journey.state import Advice, Evidence, JourneyState
from app.registry.schema import DecisionCard


class Advisor(Protocol):
    def advise(self, state: JourneyState, card: DecisionCard) -> Advice: ...


class Retriever(Protocol):
    def retrieve(self, state: JourneyState, card: DecisionCard) -> list[Evidence]: ...


class Responder(Protocol):
    name: str

    def answer(self, state: JourneyState, card: DecisionCard, question: str) -> str: ...


class MockAdvisor:
    """Repeats the card's own text; it does not analyse the project."""

    def advise(self, state: JourneyState, card: DecisionCard) -> Advice:
        return Advice(source="mock", notes={option.id: option.summary for option in card.options})


class EmptyRetriever:
    """No lecture corpus yet. An empty result is shown as "no evidence", never invented."""

    def retrieve(self, state: JourneyState, card: DecisionCard) -> list[Evidence]:
        return []


class MockResponder:
    name = "mock"

    def answer(self, state: JourneyState, card: DecisionCard, question: str) -> str:
        return "모델 미연결 상태의 고정 응답입니다. 선택지의 장단점을 참고해 주세요."


@dataclass(frozen=True)
class JourneyDeps:
    decider: Decider = field(default_factory=MockDecider)
    advisor: Advisor = field(default_factory=MockAdvisor)
    retriever: Retriever = field(default_factory=EmptyRetriever)
    responder: Responder = field(default_factory=MockResponder)
