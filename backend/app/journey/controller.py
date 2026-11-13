"""Journey Controller: picks the next card deterministically, never via an LLM (DiV P1)."""

from collections.abc import Callable, Collection, Sequence

from app.registry.schema import LAYER_STAGE

# The agent design ends with this stage, and the fork follows it (ADR-024).
AGENT_STAGE = LAYER_STAGE["model"]


def next_card(
    pending: Sequence[str], deferred: Sequence[str], focus: str | None = None
) -> str | None:
    """The card the user moved to, if still open; then undeferred cards in the given order;
    then deferred cards, oldest deferral first."""
    if focus in pending:
        return focus
    deferred_set = set(deferred)
    for card_id in pending:
        if card_id not in deferred_set:
            return card_id
    pending_set = set(pending)
    return next((card_id for card_id in deferred if card_id in pending_set), None)


def split_at_fork(
    pending: Sequence[str], stage_of: Callable[[str], int]
) -> tuple[list[str], list[str]]:
    """Open cards up to the end of the agent design, and the system cards after it."""
    early = [card_id for card_id in pending if stage_of(card_id) <= AGENT_STAGE]
    late = [card_id for card_id in pending if stage_of(card_id) > AGENT_STAGE]
    return early, late


def deploy_planned(
    scope: str | None, decided: Collection[str], stage_of: Callable[[str], int | None]
) -> bool:
    """A system card the user already decided means the fork was passed, also in journeys
    saved before the fork existed."""
    if scope is not None:
        return scope == "full"
    return any((stage_of(card_id) or 0) > AGENT_STAGE for card_id in decided)
