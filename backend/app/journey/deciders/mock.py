from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from app.journey.deciders.base import DeciderBatch, DeciderQuestion, DeciderResult

if TYPE_CHECKING:
    from app.journey.state import JourneyState


class MockDecider:
    """Answers with the question's default. A fixture, not a judgement about the project."""

    name = "mock"

    def __init__(self, overrides: Mapping[str, DeciderResult | Exception] | None = None):
        self._overrides = dict(overrides or {})

    def decide(self, state: "JourneyState", question: DeciderQuestion) -> DeciderResult:
        override = self._overrides.get(question.id)
        if isinstance(override, Exception):
            raise override
        if override is not None:
            return override
        if question.default is None:
            return DeciderResult(answer=question.choices[0], confidence=0.0)
        return DeciderResult(answer=question.default, confidence=0.9)

    def decide_many(
        self, state: "JourneyState", questions: Sequence[DeciderQuestion]
    ) -> DeciderBatch:
        """Same answers as `decide`. An override keyed by "batch" fails the whole request."""
        if isinstance(failure := self._overrides.get("batch"), Exception):
            raise failure
        return DeciderBatch(results={q.id: self.decide(state, q) for q in questions})
