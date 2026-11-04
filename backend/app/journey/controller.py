"""Journey Controller: picks the next card deterministically, never via an LLM (DiV P1)."""

from collections.abc import Sequence


def next_card(pending: Sequence[str], deferred: Sequence[str]) -> str | None:
    """Undeferred cards first, in registry order; then deferred cards, oldest deferral first."""
    deferred_set = set(deferred)
    for card_id in pending:
        if card_id not in deferred_set:
            return card_id
    pending_set = set(pending)
    return next((card_id for card_id in deferred if card_id in pending_set), None)
