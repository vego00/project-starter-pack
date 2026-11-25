"""Build decisions (ADR-026): every value a bundle needs and where it comes from, fixed in code."""

from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.registry.loader import Registry, RegistryError, load_registry
from app.registry.schema import Condition

BUILD_DECISIONS_FILE = Path(__file__).parent / "build_decisions.yaml"
Source = Literal["card", "default", "design", "ask"]
# Values worked out in code (app.journey.build_plan) rather than written here.
Compute = Literal["stack", "containers", "human_tasks", "antislop", "unknowns", "open_targets"]
Section = Literal["rules", "verify", "containers"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BuildItem(_Strict):
    id: str
    title: str
    source: Source
    card: str | None = None
    # Taken when the card was never decided (a journey saved before the card existed).
    fallback: str | None = None
    infrastructure: bool = False
    deploy: bool = False
    when: tuple[Condition, ...] = ()
    when_any: tuple[Condition, ...] = ()
    design_has: Literal["agent", "search"] | None = None
    compute: Compute | None = None
    lines: dict[Section, tuple[str, ...]] = {}
    question: str | None = None
    recommendation: str | None = None

    @model_validator(mode="after")
    def _fits_its_source(self):
        if (self.source == "card") != (self.card is not None):
            raise ValueError(f"{self.id}: only a card item names a card")
        if self.source == "ask" and self.compute is None and not self.question:
            raise ValueError(f"{self.id}: an ask item needs a question")
        if (self.infrastructure or self.deploy or self.fallback) and self.source != "card":
            raise ValueError(f"{self.id}: only a card item is shown as a card or has a fallback")
        return self


class BuildDecisions(_Strict):
    version: int = Field(ge=1)
    items: tuple[BuildItem, ...] = Field(min_length=1)


def _check_condition(registry: Registry, condition: Condition, where: str) -> None:
    if condition.card not in registry.card_ids:
        raise RegistryError(f"{where}: unknown card {condition.card}")
    options = {option.id for option in registry.card(condition.card).options}
    if unknown := set(condition.values) - options:
        raise RegistryError(f"{where}: unknown options {sorted(unknown)} on {condition.card}")


def load_build_decisions(registry: Registry, path: Path = BUILD_DECISIONS_FILE) -> BuildDecisions:
    """Fails at startup on a dangling reference, so a typo cannot drop a decision."""
    decisions = BuildDecisions.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    seen: set[str] = set()
    for item in decisions.items:
        where = f"build decision {item.id}"
        if item.id in seen:
            raise RegistryError(f"duplicate build decision {item.id}")
        seen.add(item.id)
        if item.card is not None:
            if item.card not in registry.card_ids:
                raise RegistryError(f"{where}: unknown card {item.card}")
            if item.fallback and registry.card(item.card).option(item.fallback) is None:
                raise RegistryError(f"{where}: unknown fallback {item.fallback}")
        for condition in (*item.when, *item.when_any):
            _check_condition(registry, condition, where)
    return decisions


@cache
def default_build_decisions() -> BuildDecisions:
    return load_build_decisions(load_registry())
