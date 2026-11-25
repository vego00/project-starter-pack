"""Default model IDs per provider (ADR-026 decision 7): recommendations with their source and the
day someone checked it. The bundle never fixes a model; the user confirms it."""

from datetime import date
from functools import cache
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.registry.loader import Registry, RegistryError, load_registry

PROVIDER_MODELS_FILE = Path(__file__).parent / "provider_models.yaml"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ProviderModels(_Strict):
    chat: str | None = None
    light: str | None = None
    embedding: str | None = None
    embedding_dimensions: int | None = Field(default=None, ge=1)
    source: str
    checked_at: date
    note: str | None = None
    embedding_note: str | None = None


class ProviderModelTable(_Strict):
    version: int = Field(ge=1)
    stale_after_days: int = Field(ge=1)
    providers: dict[str, ProviderModels]

    def stale_days(self, provider: str, on: date) -> int | None:
        """Days past the limit on `on`, or None while the entry is fresh or missing."""
        entry = self.providers.get(provider)
        if entry is None:
            return None
        late = (on - entry.checked_at).days - self.stale_after_days
        return late if late > 0 else None


def load_provider_models(
    registry: Registry, path: Path = PROVIDER_MODELS_FILE
) -> ProviderModelTable:
    table = ProviderModelTable.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    card = registry.card("model.provider")
    if unknown := [p for p in table.providers if card.option(p) is None]:
        raise RegistryError(f"provider models: unknown providers {unknown}")
    return table


@cache
def default_provider_models() -> ProviderModelTable:
    return load_provider_models(load_registry())
