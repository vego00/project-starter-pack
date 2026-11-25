import importlib.util
import json
from pathlib import Path

from app.journey.build_plan import plan_build
from app.journey.design import ServiceDesign
from app.journey.n8n import N8N_IMAGE, WORKFLOW_PATH, build_workflow
from app.journey.package import build_package
from app.registry.loader import load_registry

REGISTRY = load_registry()
_spec = importlib.util.spec_from_file_location(
    "validator_fixture", Path(__file__).parent / "test_design_validator.py"
)
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)


def design(implementation="n8n", provider="gemini"):
    fields = _fixture.valid_design()
    fields["provenance"]["decisions"] += [
        {"card_id": "backend.implementation", "card_version": 1, "option_id": implementation,
         "by": "user"},
    ]  # fmt: skip
    fields["provenance"]["decisions"][1]["option_id"] = provider
    # A failure path, so the error output is exercised too.
    fields["workflow"]["edges"].append(
        {"source": "intake", "target": "give_up", "condition": "입력 오류", "on_failure": True}
    )
    return ServiceDesign(**fields)


def connected(workflow):
    for source, kinds in workflow["connections"].items():
        for kind, outputs in kinds.items():
            for index, targets in enumerate(outputs):
                for target in targets:
                    yield source, kind, index, target["node"]


def test_the_card_loads_with_code_as_the_default():
    card = REGISTRY.card("backend.implementation")

    assert [option.id for option in card.options] == ["code", "n8n"]
    assert card.default_recommendation.option == "code"
    assert card.conflicts[0].severity == "warning"


def test_choosing_n8n_adds_an_importable_workflow_and_code_does_not():
    files = build_package(plan_build(design(), REGISTRY, "아이디어"))
    plain = build_package(plan_build(design("code"), REGISTRY, "아이디어"))

    assert WORKFLOW_PATH in files and WORKFLOW_PATH not in plain
    workflow = json.loads(files[WORKFLOW_PATH])
    assert {"name", "nodes", "connections", "settings"} <= set(workflow)
    assert files == build_package(plan_build(design(), REGISTRY, "아이디어"))


def test_every_node_has_the_import_fields_and_every_link_points_at_a_node():
    workflow = build_workflow(design(), "gemini")
    names = [node["name"] for node in workflow["nodes"]]

    assert len(names) == len(set(names))
    assert len({node["id"] for node in workflow["nodes"]}) == len(names)
    for node in workflow["nodes"]:
        assert {"id", "name", "type", "typeVersion", "position", "parameters"} <= set(node)
        assert len(node["position"]) == 2
    for source, kind, _, target in connected(workflow):
        assert source in names and target in names, (source, kind, target)
    assert {node.id for node in design().nodes} <= set(names)


def test_the_flow_follows_the_design():
    workflow = build_workflow(design(), "gemini")
    links = set(connected(workflow))
    by_name = {node["name"]: node for node in workflow["nodes"]}

    assert ("요청 받기", "main", 0, "intake") in links
    # grade has two conditioned exits, so a Switch with one output per condition sits after it.
    switch = by_name["grade 분기"]
    assert switch["parameters"]["numberOutputs"] == 2
    assert ("grade", "main", 0, "grade 분기") in links
    assert {t for s, _, _, t in links if s == "grade 분기"} == {"answer", "publish"}
    # The failure edge leaves through the node's error output.
    assert by_name["intake"]["onError"] == "continueErrorOutput"
    assert ("intake", "main", 1, "give_up") in links
    assert ("answer 모델", "ai_languageModel", 0, "answer") in links
    assert "최대 3회" in by_name["answer"]["notes"]


def test_a_provider_without_an_n8n_model_node_gets_no_model_node():
    workflow = build_workflow(design(provider="upstage"), "upstage")

    assert not [n for n in workflow["nodes"] if n["type"].startswith("@n8n/n8n-nodes-langchain.lm")]
    guide = next(n for n in workflow["nodes"] if n["type"] == "n8n-nodes-base.stickyNote")
    assert "HTTP Request" in guide["parameters"]["content"]


def test_the_docs_point_to_n8n_instead_of_the_code_stack():
    files = build_package(plan_build(design(), REGISTRY, "아이디어"))
    infra, build = files["docs/infrastructure.md"], files["BUILD.md"]

    assert N8N_IMAGE in infra and "127.0.0.1:5678" in infra
    assert "FastAPI" not in infra and "- 앱:" not in infra
    assert f"n8n import:workflow --input={WORKFLOW_PATH}" in build
