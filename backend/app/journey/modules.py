"""The build order (ADR-022): modules, their start conditions and completion criteria.

Derived from the decisions and the module rules on every read, never stored, so it cannot drift
from what was decided. Goal, scope and tasks stay empty until a conversation or the design fills
them in a later step.
"""

from collections.abc import Mapping
from typing import Literal

from pydantic import BaseModel

from app.registry.loader import Registry
from app.registry.modules import ModuleRule, ModuleRules
from app.registry.schema import Condition

Source = Literal["rule", "design", "chat", "open"]


class ModuleItem(BaseModel):
    text: str
    how: str | None = None
    source: Source


class ModuleGate(ModuleItem):
    # Said when someone asks to skip it, since a rule's gate cannot be dropped.
    why: str


class ModuleCriterion(ModuleItem):
    kind: Literal["quantitative", "qualitative"]


class ModuleAfter(BaseModel):
    module: str
    gate_only: bool = False


class ModulePlan(BaseModel):
    id: str
    name: str
    stack: list[str]
    cards: list[str]
    # Modules in the same column can run side by side.
    column: int
    after: list[ModuleAfter]
    goal: ModuleItem | None = None
    include: list[ModuleItem] = []
    exclude: list[ModuleItem] = []
    gates: list[ModuleGate]
    criteria: list[ModuleCriterion]
    tasks: list[str] = []


def _holds(conditions: tuple[Condition, ...], choices: Mapping[str, str]) -> bool:
    return all(c.matches(choices.get(c.card)) for c in conditions)


def _present(rule: ModuleRule, choices: Mapping[str, str]) -> bool:
    if not rule.present_when_any:
        return True
    return any(c.matches(choices.get(c.card)) for c in rule.present_when_any)


def _option_name(registry: Registry, card_id: str, choices: Mapping[str, str]) -> str | None:
    option_id = choices.get(card_id)
    return registry.card(card_id).option(option_id).name if option_id else None


def build_module_plan(
    registry: Registry, rules: ModuleRules, choices: Mapping[str, str]
) -> list[ModulePlan]:
    present = [rule for rule in rules.modules if _present(rule, choices)]
    kept = {rule.id for rule in present}
    columns: dict[str, int] = {}
    plans = []
    for rule in present:
        after = [
            ModuleAfter(module=a.module, gate_only=a.gate_only)
            for a in rule.after
            if a.module in kept
        ]
        # Waiting only for another module's start conditions puts this one beside it.
        columns[rule.id] = max(
            (columns[a.module] + (0 if a.gate_only else 1) for a in after), default=0
        )
        named = _option_name(registry, rule.name_from, choices) if rule.name_from else None
        plans.append(
            ModulePlan(
                id=rule.id,
                name=named or rule.name,
                stack=[
                    name
                    for card_id in rule.cards
                    if (name := _option_name(registry, card_id, choices))
                ],
                cards=list(rule.cards),
                column=columns[rule.id],
                after=after,
                gates=[
                    ModuleGate(text=gate.text, why=gate.why, source="rule")
                    for gate in rule.gates
                    if _holds(gate.when, choices)
                ],
                criteria=[
                    ModuleCriterion(
                        kind=criterion.kind,
                        text=criterion.text,
                        how=criterion.how,
                        source="open" if criterion.target == "open" else "rule",
                    )
                    for criterion in rule.criteria
                    if _holds(criterion.when, choices)
                ],
            )
        )
    return plans
