from collections.abc import Mapping
from typing import TYPE_CHECKING

from app.journey.deciders.base import DeciderQuestion, DeciderResult

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
