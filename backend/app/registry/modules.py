"""Module rules (ADR-022): the start conditions and base completion criteria no model can drop."""

from functools import cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.registry.loader import Registry, RegistryError, load_registry
from app.registry.schema import Condition

MODULES_FILE = Path(__file__).parent / "modules.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GateRule(_Strict):
    text: str
    why: str
    when: tuple[Condition, ...] = ()


class CriterionRule(_Strict):
    kind: Literal["quantitative", "qualitative"]
    text: str
    how: str
    # "open" asks the user for the target; a rule never supplies one.
    target: Literal["open"] | None = None
    when: tuple[Condition, ...] = ()


class AfterRule(_Strict):
    module: str
    gate_only: bool = False


class ModuleRule(_Strict):
    id: str
    name: str
    name_from: str | None = None
    cards: tuple[str, ...] = Field(min_length=1)
    present_when_any: tuple[Condition, ...] = ()
    after: tuple[AfterRule, ...] = ()
    gates: tuple[GateRule, ...] = Field(min_length=1)
    criteria: tuple[CriterionRule, ...] = Field(min_length=1)


class ModuleRules(_Strict):
    version: int = Field(ge=1)
    modules: tuple[ModuleRule, ...] = Field(min_length=1)


def _check_condition(registry: Registry, condition: Condition, where: str) -> None:
    if condition.card not in registry.card_ids:
        raise RegistryError(f"{where}: unknown card {condition.card}")
    options = {option.id for option in registry.card(condition.card).options}
    if unknown := set(condition.in_ or condition.not_in or ()) - options:
        raise RegistryError(f"{where}: unknown options {sorted(unknown)} on {condition.card}")


def load_module_rules(registry: Registry, path: Path = MODULES_FILE) -> ModuleRules:
    """Fails at startup on a dangling reference, so a typo cannot drop a start condition."""
    rules = ModuleRules.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    seen: set[str] = set()
    for module in rules.modules:
        where = f"module {module.id}"
        if module.id in seen:
            raise RegistryError(f"duplicate module {module.id}")
        if unknown := set(module.cards) - set(registry.card_ids):
            raise RegistryError(f"{where}: unknown cards {sorted(unknown)}")
        if module.name_from and module.name_from not in module.cards:
            raise RegistryError(f"{where}: name_from must be one of its cards")
        # Pointing only backwards keeps the order free of cycles.
        if unknown := {after.module for after in module.after} - seen:
            raise RegistryError(f"{where}: after must name earlier modules, not {sorted(unknown)}")
        conditions = [
            *module.present_when_any,
            *(c for gate in module.gates for c in gate.when),
            *(c for criterion in module.criteria for c in criterion.when),
        ]
        for condition in conditions:
            _check_condition(registry, condition, where)
        seen.add(module.id)
    return rules


@cache
def default_module_rules() -> ModuleRules:
    """Checked against every card on disk, so a journey that uses fewer cards still reads them."""
    return load_module_rules(load_registry())
