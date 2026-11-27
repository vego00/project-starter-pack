"""Module plan (ADR-022): modules, start conditions and criteria come from rules and decisions."""

from pathlib import Path

import pytest
from app.config import Settings
from app.journey.blueprint import EXAMPLES
from app.journey.modules import build_module_plan
from app.main import create_app
from app.registry.loader import Registry, RegistryError, load_registry
from app.registry.modules import MODULES_FILE, load_module_rules
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver

REGISTRY = load_registry()
RULES = load_module_rules(REGISTRY)
CHOICES = {example_id: choices for example_id, _, _, choices in EXAMPLES}


def plan(choices):
    return {module.id: module for module in build_module_plan(REGISTRY, RULES, choices)}


def gate_texts(module):
    return [gate.text for gate in module.gates]


def test_the_rules_load_against_the_cards():
    assert [module.id for module in RULES.modules] == ["data", "agent", "api", "client", "ops"]


@pytest.mark.parametrize(
    ("change", "message"),
    [
        (("cards: [backend.execution]", "cards: [backend.nothing]"), "unknown cards"),
        (
            ("in: [web]}]\n        kind: asked", "in: [webb]}]\n        kind: asked"),
            "unknown options",
        ),
        (("after: [{module: data}]", "after: [{module: ops}]"), "earlier modules"),
    ],
)
def test_a_broken_rule_stops_the_start(tmp_path: Path, change, message):
    old, new = change
    text = MODULES_FILE.read_text(encoding="utf-8")
    assert old in text
    broken = tmp_path / "modules.yaml"
    broken.write_text(text.replace(old, new, 1), encoding="utf-8")

    with pytest.raises(RegistryError, match=message):
        load_module_rules(REGISTRY, broken)


def test_a_registry_with_fewer_cards_still_gets_a_plan():
    few = Registry(c for c in REGISTRY.cards if c.layer not in ("product", "ops"))

    modules = build_module_plan(few, RULES, {"agent.topology": "single"})

    assert [module.id for module in modules] == ["agent", "api", "client", "ops"]
    assert modules[2].name == "사용자 접점"


def test_modules_that_wait_only_for_a_contract_share_a_column():
    modules = plan(CHOICES["team"])

    columns = {module_id: module.column for module_id, module in modules.items()}
    assert columns == {"data": 0, "agent": 1, "api": 2, "client": 2, "ops": 3}
    assert [a.model_dump() for a in modules["client"].after] == [
        {"module": "api", "gate_only": True}
    ]


def test_a_project_with_nothing_to_store_has_no_data_module():
    choices = {
        **CHOICES["basic"],
        "data.primary_db": "none",
        "data.vector_store": "none",
        "data.checkpointer": "memory",
    }

    modules = plan(choices)

    assert "data" not in modules
    assert modules["agent"].column == 0
    assert modules["agent"].after == []


def test_start_conditions_follow_the_decisions():
    team, private = plan(CHOICES["team"]), plan(CHOICES["private"])

    assert any("API 키" in text for text in gate_texts(team["agent"]))
    assert not any("API 키" in text for text in gate_texts(private["agent"]))
    assert any("모델 파일" in text for text in gate_texts(private["agent"]))
    assert any("대화 흐름" in text for text in gate_texts(team["client"]))
    # The first build is local, so cloud cost limits wait in the bundle's "배포 (나중)" (ADR-026).
    assert not any("비용 상한과 알림" in text for text in gate_texts(team["ops"]))


def test_the_screen_module_is_named_after_the_chosen_surface_and_waits_for_a_design():
    basic = plan(CHOICES["basic"])["client"]

    assert basic.name == "웹 화면"
    # Set in build preparation instead of a mock-up approval (ADR-026 decision 4).
    assert basic.gates[0].kind == "asked" and basic.gates[0].asks == "screen_layout"
    assert basic.gates[0].why


def test_every_rule_part_is_marked_and_no_target_is_invented():
    for module in plan(CHOICES["team"]).values():
        assert all(gate.source == "rule" for gate in module.gates)
        assert module.goal is None and module.include == [] and module.tasks == []
        for criterion in module.criteria:
            assert criterion.source in ("rule", "open")
            assert criterion.how

    agent = plan(CHOICES["team"])["agent"]
    open_items = [c for c in agent.criteria if c.source == "open"]
    assert [c.text for c in open_items] == ["답변 응답 시간"]


def test_the_stack_names_the_chosen_options():
    assert plan(CHOICES["team"])["data"].stack == [
        "데이터 저장소: PostgreSQL",
        "검색 저장소: pgvector (PostgreSQL 확장)",
        "상태 저장: PostgreSQL 체크포인터",
    ]


def test_the_journey_view_carries_the_module_plan():
    app = create_app(Settings(_env_file=None), checkpointer=InMemorySaver(), registry=REGISTRY)
    with TestClient(app) as client:
        view = client.post(
            "/api/v1/journeys", json={"idea": "강의 자료로 질문에 답하는 서비스"}
        ).json()

    ids = [module["id"] for module in view["modules"]]
    assert {"agent", "api", "client", "ops"} <= set(ids)
    assert all(module["gates"] for module in view["modules"])


def test_an_api_model_needs_its_key_kept_out_of_the_repository():
    modules = plan({**CHOICES["team"], "model.provider": "exaone"})

    assert any("API 키" in text for text in gate_texts(modules["agent"]))
