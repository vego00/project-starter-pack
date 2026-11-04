"""Loads decision cards and checks rules across cards, failing at startup rather than mid-journey."""

from collections.abc import Iterable, Iterator
from pathlib import Path

import yaml

from app.registry.schema import LAYERS, Condition, DecisionCard

CARDS_DIR = Path(__file__).parent / "cards"


class RegistryError(ValueError):
    pass


class Registry:
    def __init__(self, cards: Iterable[DecisionCard]):
        # Journey order: layer, then the card's order, then card_id to keep it stable.
        self.cards = tuple(sorted(cards, key=lambda c: (LAYERS.index(c.layer), c.order, c.card_id)))
        self._by_id = {card.card_id: card for card in self.cards}
        if len(self._by_id) != len(self.cards):
            raise RegistryError("duplicate card_id")
        self._validate_rules()

    @property
    def card_ids(self) -> tuple[str, ...]:
        return tuple(card.card_id for card in self.cards)

    def card(self, card_id: str) -> DecisionCard:
        return self._by_id[card_id]

    def _conditions(self, card: DecisionCard) -> Iterator[tuple[str, Condition]]:
        for rule in (*card.requires, *card.conflicts, *card.implies):
            for condition in rule.when:
                yield rule.id, condition
        for rule in card.requires:
            yield rule.id, rule.require

    def _validate_rules(self) -> None:
        seen: set[str] = set()
        for card in self.cards:
            for rule in (*card.requires, *card.conflicts, *card.implies):
                if rule.id in seen:
                    raise RegistryError(f"duplicate rule id {rule.id}")
                seen.add(rule.id)
            for rule_id, condition in self._conditions(card):
                self._check_ref(rule_id, condition.card, condition.values)
            for rule in card.implies:
                self._check_ref(rule.id, rule.then.card, (rule.then.option,))

    def _check_ref(self, rule_id: str, card_id: str, option_ids: tuple[str, ...]) -> None:
        target = self._by_id.get(card_id)
        if target is None:
            raise RegistryError(f"rule {rule_id}: unknown card {card_id}")
        for option_id in option_ids:
            if target.option(option_id) is None:
                raise RegistryError(f"rule {rule_id}: unknown option {card_id}={option_id}")


def load_registry(cards_dir: Path = CARDS_DIR, *, require_all_layers: bool = True) -> Registry:
    cards = [
        DecisionCard.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
        for path in sorted(cards_dir.glob("*.yaml"))
    ]
    registry = Registry(cards)
    if require_all_layers and (missing := set(LAYERS) - {card.layer for card in registry.cards}):
        raise RegistryError(f"layers without a card: {sorted(missing)}")
    return registry
