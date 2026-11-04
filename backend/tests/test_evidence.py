from uuid import uuid4

import pytest
from app.config import Settings
from app.journey.services import CuratedRetriever, EmptyRetriever, LLMAdvisor, build_deps
from app.journey.state import JourneyState, ProjectSpec
from app.registry.evidence import load_catalog
from app.registry.loader import RegistryError, load_registry

REGISTRY = load_registry()
CATALOG = load_catalog(REGISTRY)


def make_state():
    return JourneyState(
        journey_id=uuid4(), project_spec=ProjectSpec(idea="가상의 예시 프로젝트 설명")
    )


def retrieve(card_id):
    return CuratedRetriever(CATALOG).retrieve(make_state(), REGISTRY.card(card_id))


def test_only_linked_cards_get_evidence():
    with_evidence = {c.card_id for c in REGISTRY.cards if retrieve(c.card_id)}

    assert with_evidence == {"agent.hitl", "agent.topology"}


def test_evidence_says_what_it_is_and_where():
    item = retrieve("agent.hitl")[0]

    assert (item.title, item.kind) == ("LG전자 AX Work", "personal_note")
    assert item.location == "Ch. 2 Role Shift"
    assert item.url.startswith("https://app.notion.com/")


def test_catalog_marks_every_source_private_and_reviewed():
    assert {source.permission for source in CATALOG.sources} == {"owner_only"}
    assert all(source.checked_on for source in CATALOG.sources)


def test_notes_are_off_unless_the_owner_turns_them_on():
    assert isinstance(build_deps(Settings(_env_file=None), REGISTRY).retriever, EmptyRetriever)

    owner = build_deps(Settings(_env_file=None, evidence_scope="owner"), REGISTRY)
    assert isinstance(owner.retriever, CuratedRetriever)


def test_real_model_settings_keep_the_chosen_retriever():
    deps = build_deps(
        Settings(_env_file=None, provider="gemini", gemini_api_key="k", gemini_model="m"),
        REGISTRY,
    )

    assert isinstance(deps.advisor, LLMAdvisor)
    assert isinstance(deps.retriever, EmptyRetriever)


def write(tmp_path, text):
    path = tmp_path / "evidence.yaml"
    path.write_text(text, encoding="utf-8")
    return path


SOURCE = """
sources:
  - {source_id: s, title: t, kind: personal_note, url: u, checked_on: 2026-11-04,
     permission: owner_only}
"""


@pytest.mark.parametrize(
    ("links", "message"),
    [
        ("[{source_id: missing, topics: [langgraph], location: l, why: w}]", "unknown source"),
        ("[{source_id: s, topics: [typo-topic], location: l, why: w}]", "no card uses"),
    ],
)
def test_dangling_references_fail_at_startup(tmp_path, links, message):
    path = write(tmp_path, f"{SOURCE}\nlinks: {links}\n")

    with pytest.raises(RegistryError, match=message):
        load_catalog(REGISTRY, path)


def test_duplicate_sources_fail_at_startup(tmp_path):
    path = write(tmp_path, f"{SOURCE}{SOURCE.replace('sources:', '')}\nlinks: []\n")

    with pytest.raises(RegistryError, match="duplicate"):
        load_catalog(REGISTRY, path)


def test_note_text_cannot_be_stored_in_a_link(tmp_path):
    path = write(
        tmp_path,
        f"{SOURCE}\nlinks: [{{source_id: s, topics: [langgraph], location: l, why: w, excerpt: x}}]",
    )

    with pytest.raises(ValueError, match="excerpt"):
        load_catalog(REGISTRY, path)


def test_model_prompts_never_include_notes():
    state = make_state()
    state.evidence = retrieve("agent.hitl")

    from app.journey.prompts import project_context

    assert "evidence" not in project_context(state, REGISTRY)
