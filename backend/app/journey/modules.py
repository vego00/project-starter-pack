"""The build order (ADR-022): modules, their start conditions and completion criteria.

Derived from the decisions and the module rules on every read, so it cannot drift from what was
decided. Only what people said (goal, scope, targets) is stored, as notes laid over the plan.
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
    kind: Literal["human", "rule", "asked"] = "human"
    asks: str | None = None


class ModuleCriterion(ModuleItem):
    kind: Literal["quantitative", "qualitative"]
    # The rule left the target open; a conversation or an edit fills `target`.
    needs_target: bool = False
    target: str | None = None


class ModuleNote(BaseModel):
    """What a person said about a module. Rule parts are never stored, only recomputed."""

    goal: str | None = None
    include: list[str] = []
    exclude: list[str] = []
    targets: dict[str, str] = {}  # criterion text -> target


class ModuleTurn(BaseModel):
    role: Literal["user", "assistant"]
    text: str
    changes: list[str] = []
    rejected: list[str] = []


class ModuleChange(BaseModel):
    """One field a model or a person wants to set. Lists are sent whole, not as additions."""

    module: str
    field: Literal["goal", "include", "exclude", "target"]
    value: str = ""
    items: list[str] = []
    criterion: str = ""


FIELD_LABELS = {"goal": "목표", "include": "만들 것", "exclude": "안 만들 것", "target": "목표치"}
MAX_GOAL = 200
MAX_ITEM = 120
MAX_ITEMS = 12
MAX_TARGET = 60


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


def _tidy(text: str) -> str:
    return " ".join(text.split())


def apply_module_changes(
    plan: list[ModulePlan], notes: Mapping[str, ModuleNote], changes: list[ModuleChange]
) -> tuple[dict[str, ModuleNote], list[str], list[str]]:
    """The validator for what a model or a person writes: rule parts and unmeasurable targets
    never get in. Returns the new notes, what was applied and why the rest was not."""
    modules = {module.id: module for module in plan}
    updated = {module_id: note.model_copy(deep=True) for module_id, note in notes.items()}
    applied: list[str] = []
    rejected: list[str] = []
    for change in changes:
        module = modules.get(change.module)
        if module is None:
            rejected.append(f"'{change.module}' 모듈은 만드는 순서에 없어요.")
            continue
        label = f"{module.name} · {FIELD_LABELS[change.field]}"
        note = updated.setdefault(module.id, ModuleNote())
        if change.field == "goal":
            goal = _tidy(change.value)
            if not 0 < len(goal) <= MAX_GOAL:
                rejected.append(f"{label}: 비어 있거나 {MAX_GOAL}자를 넘어요.")
                continue
            note.goal = goal
        elif change.field in ("include", "exclude"):
            items = list(dict.fromkeys(_tidy(item) for item in change.items if item.strip()))
            if len(items) > MAX_ITEMS or any(len(item) > MAX_ITEM for item in items):
                rejected.append(
                    f"{label}: {MAX_ITEMS}개, 항목마다 {MAX_ITEM}자까지 적을 수 있어요."
                )
                continue
            setattr(note, change.field, items)
        else:
            open_texts = {c.text for c in module.criteria if c.needs_target}
            target = _tidy(change.value)
            if change.criterion not in open_texts:
                rejected.append(f"{label}: 정할 값이 있는 기준이 아니에요.")
                continue
            # A target nobody can measure stays open, so it is asked again.
            if not any(ch.isdigit() for ch in target) or len(target) > MAX_TARGET:
                rejected.append(
                    f"{label}: 재서 확인할 수 있는 값이 아니라 정할 값으로 남겨 뒀어요."
                )
                continue
            note.targets[change.criterion] = target
        applied.append(label)
    return updated, list(dict.fromkeys(applied)), rejected


def build_module_plan(
    registry: Registry,
    rules: ModuleRules,
    choices: Mapping[str, str],
    notes: Mapping[str, ModuleNote] | None = None,
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
        note = (notes or {}).get(rule.id) or ModuleNote()
        plans.append(
            ModulePlan(
                id=rule.id,
                name=named or rule.name,
                stack=[
                    f"{registry.card(card_id).title}: {name}"
                    for card_id in rule.cards
                    if (name := _option_name(registry, card_id, choices))
                ],
                cards=list(rule.cards),
                column=columns[rule.id],
                after=after,
                goal=ModuleItem(text=note.goal, source="chat") if note.goal else None,
                include=[ModuleItem(text=text, source="chat") for text in note.include],
                exclude=[ModuleItem(text=text, source="chat") for text in note.exclude],
                gates=[
                    ModuleGate(
                        text=gate.text, why=gate.why, source="rule", kind=gate.kind, asks=gate.asks
                    )
                    for gate in rule.gates
                    if _holds(gate.when, choices)
                ],
                criteria=[
                    ModuleCriterion(
                        kind=criterion.kind,
                        text=criterion.text,
                        how=criterion.how,
                        needs_target=criterion.target == "open",
                        target=note.targets.get(criterion.text),
                        source=(
                            "rule"
                            if criterion.target != "open"
                            else "chat"
                            if criterion.text in note.targets
                            else "open"
                        ),
                    )
                    for criterion in rule.criteria
                    if _holds(criterion.when, choices)
                ],
            )
        )
    return plans
