"""Curated evidence: reviewed note sections, ready to be replaced by search as notes accumulate."""

from datetime import date
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.registry.loader import Registry, RegistryError

EVIDENCE_FILE = Path(__file__).parent / "evidence.yaml"

Permission = Literal["owner_only"]


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class EvidenceSource(_Strict):
    source_id: str
    title: str
    kind: Literal["personal_note"]
    url: str
    checked_on: date
    permission: Permission


class EvidenceLink(_Strict):
    source_id: str
    topics: tuple[str, ...] = Field(min_length=1)
    location: str
    why: str


class EvidenceCatalog(_Strict):
    sources: tuple[EvidenceSource, ...]
    links: tuple[EvidenceLink, ...]

    def source(self, source_id: str) -> EvidenceSource:
        return next(source for source in self.sources if source.source_id == source_id)


def load_catalog(registry: Registry, path: Path = EVIDENCE_FILE) -> EvidenceCatalog:
    """Fails at startup on a dangling reference, so a typo cannot silently hide evidence."""
    catalog = EvidenceCatalog.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    source_ids = [source.source_id for source in catalog.sources]
    if len(source_ids) != len(set(source_ids)):
        raise RegistryError("duplicate evidence source_id")
    topics = {topic for card in registry.cards for topic in card.learning_refs}
    for link in catalog.links:
        if link.source_id not in source_ids:
            raise RegistryError(f"evidence link to unknown source {link.source_id}")
        if unknown := set(link.topics) - topics:
            raise RegistryError(f"evidence topics no card uses: {sorted(unknown)}")
    return catalog
