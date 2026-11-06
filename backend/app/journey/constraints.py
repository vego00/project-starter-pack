"""Constraint Engine: requires / implies / conflicts as pure, deterministic rules (no LLM)."""

from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from app.registry.loader import Registry
from app.registry.schema import Condition


class Conflict(BaseModel):
    rule_id: str
    severity: Literal["error", "warning"]
    message: str
    card_ids: list[str]


class ImpliedChoice(BaseModel):
    option_id: str
    rule_id: str
    message: str


@dataclass(frozen=True)
class ConstraintResult:
    implied: dict[str, ImpliedChoice]
    conflicts: list[Conflict]
    blocked: dict[str, dict[str, str]]  # card_id -> option_id -> reason
    pending: list[str]


@dataclass(frozen=True)
class Impact:
    implied: dict[str, ImpliedChoice]
    conflicts: list[Conflict]


@dataclass(frozen=True)
class _Clause:
    """A combination that must not hold. `requires` is stored as `when AND NOT require`."""

    rule_id: str
    severity: Literal["error", "warning"]
    message: str
    conditions: tuple[Condition, ...]


def _clauses(registry: Registry) -> Iterator[_Clause]:
    for card in registry.cards:
        for rule in card.requires:
            conditions = (*rule.when, rule.require.negated())
            yield _Clause(rule.id, "error", rule.message, conditions)
        for rule in card.conflicts:
            yield _Clause(rule.id, rule.severity, rule.message, rule.when)


def _apply_implies(
    registry: Registry, chosen: Mapping[str, str]
) -> tuple[dict[str, ImpliedChoice], list[Conflict]]:
    implied: dict[str, ImpliedChoice] = {}
    conflicts: list[Conflict] = []
    effective = dict(chosen)
    rules = [rule for card in registry.cards for rule in card.implies]
    fired: set[str] = set()
    # Terminates: effective only grows and each rule fires at most once.
    changed = True
    while changed:
        changed = False
        for rule in rules:
            if rule.id in fired or not all(c.matches(effective.get(c.card)) for c in rule.when):
                continue
            fired.add(rule.id)
            changed = True
            target, option_id = rule.then.card, rule.then.option
            current = effective.get(target)
            if current is None:
                effective[target] = option_id
                implied[target] = ImpliedChoice(
                    option_id=option_id, rule_id=rule.id, message=rule.message
                )
            elif current != option_id:
                # Never overwrite a decision: changing it is the user's call.
                conflicts.append(
                    Conflict(
                        rule_id=rule.id,
                        severity="error",
                        message=rule.message,
                        card_ids=[*(c.card for c in rule.when), target],
                    )
                )
    return implied, conflicts


def evaluate(registry: Registry, chosen: Mapping[str, str]) -> ConstraintResult:
    """`chosen` holds user decisions only, so implied choices are always recomputed from them.

    Reverting a decision therefore also reverts whatever it implied.
    """
    implied, conflicts = _apply_implies(registry, chosen)
    effective = {**chosen, **{card_id: i.option_id for card_id, i in implied.items()}}
    blocked: dict[str, dict[str, str]] = {}

    for clause in _clauses(registry):
        open_conditions = [c for c in clause.conditions if c.card not in effective]
        if not all(c.matches(effective[c.card]) for c in clause.conditions if c.card in effective):
            continue
        if not open_conditions:
            conflicts.append(
                Conflict(
                    rule_id=clause.rule_id,
                    severity=clause.severity,
                    message=clause.message,
                    card_ids=list(dict.fromkeys(c.card for c in clause.conditions)),
                )
            )
        elif len(open_conditions) == 1 and clause.severity == "error":
            # One undecided condition left: the options completing the clause are unavailable.
            last = open_conditions[0]
            for option in registry.card(last.card).options:
                if last.matches(option.id):
                    blocked.setdefault(last.card, {}).setdefault(option.id, clause.message)

    pending = [card_id for card_id in registry.card_ids if card_id not in effective]
    return ConstraintResult(implied, conflicts, blocked, pending)


def revived(registry: Registry, effective: Mapping[str, str], skipped: Collection[str]) -> set[str]:
    """Skipped cards that a rule on decided cards still points at, so they must be asked (ADR-018).

    Only requires rules and error conflicts whose decided conditions all hold count; warnings do not.
    """
    skipped = set(skipped) - set(effective)
    back: set[str] = set()
    for card in registry.cards:
        for rule in card.requires:
            target = rule.require.card
            if target in skipped and all(c.matches(effective.get(c.card)) for c in rule.when):
                back.add(target)
        for rule in card.conflicts:
            undecided = {c.card for c in rule.when if c.card not in effective}
            decided = [c for c in rule.when if c.card in effective]
            if (
                rule.severity == "error"
                and decided
                and undecided <= skipped
                and all(c.matches(effective[c.card]) for c in decided)
            ):
                back |= undecided
    return back


def preview(registry: Registry, chosen: Mapping[str, str], card_id: str, option_id: str) -> Impact:
    """What choosing this option would newly imply or trigger ("선택하면 같이 바뀌는 것")."""
    before = evaluate(registry, chosen)
    after = evaluate(registry, {**chosen, card_id: option_id})
    known_rules = {conflict.rule_id for conflict in before.conflicts}
    return Impact(
        implied={k: v for k, v in after.implied.items() if k not in before.implied},
        conflicts=[c for c in after.conflicts if c.rule_id not in known_rules],
    )
