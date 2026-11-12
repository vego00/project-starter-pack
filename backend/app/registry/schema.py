"""Decision Card contract (see Decision Registry in Notion)."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

LAYERS = ("agent", "model", "data", "backend", "devops", "mlops", "cloud", "product", "ops")
Layer = Literal["agent", "model", "data", "backend", "devops", "mlops", "cloud", "product", "ops"]
# Project stages (ADR-021), ordered so that changing an earlier one can invalidate a later one.
LAYER_STAGE = {
    "product": 3,
    "agent": 4,
    # The agent graph needs a model, so the provider closes the agent stage (ADR-024).
    "model": 4,
    "data": 5,
    "backend": 5,
    "devops": 5,
    "mlops": 5,
    "cloud": 5,
    "ops": 6,
}
Level = Literal["low", "medium", "high"]


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Condition(_Frozen):
    """True only when `card` is decided with a matching option; undecided is never a match."""

    card: str
    in_: tuple[str, ...] | None = Field(default=None, alias="in", min_length=1)
    not_in: tuple[str, ...] | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def _exactly_one(self):
        if (self.in_ is None) == (self.not_in is None):
            raise ValueError("condition needs exactly one of `in` / `not_in`")
        return self

    @property
    def values(self) -> tuple[str, ...]:
        return self.in_ if self.in_ is not None else self.not_in  # type: ignore[return-value]

    def matches(self, option_id: str | None) -> bool:
        if option_id is None:
            return False
        return option_id in self.in_ if self.in_ is not None else option_id not in self.not_in

    def negated(self) -> "Condition":
        if self.in_ is not None:
            return Condition(card=self.card, not_in=self.in_)
        return Condition(card=self.card, in_=self.not_in)


class RequiresRule(_Frozen):
    id: str
    when: tuple[Condition, ...] = Field(min_length=1)
    require: Condition
    message: str


class ConflictRule(_Frozen):
    id: str
    when: tuple[Condition, ...] = Field(min_length=2)
    severity: Literal["error", "warning"] = "error"
    message: str


class ImpliedOption(_Frozen):
    card: str
    option: str


class ImpliesRule(_Frozen):
    id: str
    when: tuple[Condition, ...] = Field(min_length=1)
    then: ImpliedOption
    message: str


class CardOption(_Frozen):
    id: str
    name: str
    summary: str
    pros: tuple[str, ...] = ()
    cons: tuple[str, ...] = ()
    learning_difficulty: Level
    ops_burden: Level
    cost_nature: str


class DefaultRecommendation(_Frozen):
    option: str
    reason: str


class DecisionCard(_Frozen):
    card_id: str
    version: int = Field(ge=1)
    layer: Layer
    order: int = 50  # Position within the layer; lower comes first.
    title: str = Field(min_length=1)  # Short label; a layer can hold several cards.
    question: str
    options: tuple[CardOption, ...] = Field(min_length=2)
    signals: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    # Project info this card reads (ADR-024); a blank one is asked on this card.
    uses: tuple[str, ...] = ()
    requires: tuple[RequiresRule, ...] = ()
    conflicts: tuple[ConflictRule, ...] = ()
    implies: tuple[ImpliesRule, ...] = ()
    default_recommendation: DefaultRecommendation
    learning_refs: tuple[str, ...] = ()
    div_refs: tuple[str, ...] = ()
    artifacts: dict[str, tuple[str, ...]] = Field(default_factory=dict)
    sources: tuple[str, ...] = ()
    checked_at: date | None = None

    @model_validator(mode="after")
    def _internally_consistent(self):
        if not self.card_id.startswith(f"{self.layer}."):
            raise ValueError(f"{self.card_id}: card_id must start with layer '{self.layer}.'")
        ids = [option.id for option in self.options]
        if len(ids) != len(set(ids)):
            raise ValueError(f"{self.card_id}: duplicate option id")
        referenced = {self.default_recommendation.option, *self.signals, *self.artifacts}
        if unknown := referenced - set(ids):
            raise ValueError(f"{self.card_id}: unknown option ids {sorted(unknown)}")
        return self

    @property
    def stage(self) -> int:
        return LAYER_STAGE[self.layer]

    def option(self, option_id: str) -> CardOption | None:
        return next((option for option in self.options if option.id == option_id), None)
