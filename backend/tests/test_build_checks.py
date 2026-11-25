"""ADR-026 step 2: one reproduction per consistency rule, and the three build trials of
2026-11-24 (C1, C2, C4-design) rebuilt from what their build notes report."""

import importlib.util
from pathlib import Path

from app.journey.build_checks import build_issues, design_issues
from app.journey.build_plan import plan_build
from app.journey.design import ServiceDesign
from app.journey.design_validator import validate_design
from app.journey.package import build_package
from app.journey.state import ProjectSpec
from app.registry.loader import load_registry

REGISTRY = load_registry()
_spec = importlib.util.spec_from_file_location(
    "validator_fixture", Path(__file__).parent / "test_design_validator.py"
)
_fixture = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_fixture)
TEAM = ProjectSpec(idea="강의 과제 피드백을 돕는 서비스", deployment_target="small_group",
                   expected_users=31)  # fmt: skip


def fields(change=None):
    data = _fixture.valid_design()
    if change:
        change(data)
    return data


def with_choices(data, **choices):
    decisions = {d["card_id"]: d for d in data["provenance"]["decisions"]}
    for card_id, option_id in choices.items():
        decisions[card_id] = {"card_id": card_id, "card_version": REGISTRY.card(card_id).version,
                              "option_id": option_id, "by": "user"}  # fmt: skip
    data["provenance"]["decisions"] = list(decisions.values())
    return ServiceDesign(**data)


def rules(design, chosen, project=None):
    return {issue.rule_id for issue in build_issues(design, chosen, project)}


def vector_tool(data):
    _fixture.by_id(data, "answer")["tools"] = [
        {
            "name": "search_idea",
            "access": "read",
            "reason": "pgvector 유사도 검색으로 메모를 찾는다",
        }
    ]


def no_empty_case(data):
    data["eval_cases"] = data["eval_cases"][:1]


# One reproduction per rule


def test_vector_words_without_a_vector_store_are_a_design_error():
    design = ServiceDesign(**fields(vector_tool))

    assert "decision.vector_store_not_chosen" in rules(design, {"data.vector_store": "none"})
    assert "decision.vector_store_not_chosen" not in rules(
        design, {"data.vector_store": "pgvector"}
    )


def test_an_unknown_reopening_a_decided_store_is_a_design_error():
    def reopen(data):
        data["unknowns"] = [{"text": "pgvector를 쓸지 정해야 합니다", "blocks_confirmation": False}]

    design = ServiceDesign(**fields(reopen))

    assert "decision.vector_store_reopened" in rules(design, {"data.vector_store": "none"})
    assert "decision.vector_store_reopened" not in rules(design, {})


def test_a_search_design_without_a_no_result_case_is_warned():
    design = ServiceDesign(**fields(lambda d: (vector_tool(d), no_empty_case(d))))
    found = {i.rule_id: i for i in build_issues(design, {"data.vector_store": "pgvector"})}

    assert found["eval.no_empty_result_case"].severity == "warning"
    assert "eval.no_empty_result_case" not in rules(
        ServiceDesign(**fields(vector_tool)), {"data.vector_store": "pgvector"}
    )


def test_a_vector_store_nothing_searches_is_warned():
    design = ServiceDesign(**fields())

    assert "decision.vector_store_unused" in rules(design, {"data.vector_store": "pgvector"})


def test_a_serving_no_node_uses_is_warned():
    design = ServiceDesign(**fields())
    both = {"model.provider": "upstage", "mlops.model_serving": "ollama"}

    assert "decision.serving_unused" in rules(design, both)
    assert "decision.serving_unused" not in rules(design, {**both, "model.provider": "ollama"})


def test_a_web_service_for_many_users_without_login_is_asked():
    design = ServiceDesign(**fields())
    web = {"product.surface": "web"}

    assert "access.many_users_no_login" in rules(design, web, TEAM)
    assert "access.many_users_no_login" not in rules(design, web, None)
    assert "access.many_users_no_login" not in rules(design, {"product.surface": "messenger"}, TEAM)


def test_a_deploy_task_in_the_first_build_is_warned_unless_local_is_allowed():
    def deploy_task(data):
        data["tasks"][0]["inputs"] = "GCP PostgreSQL 연결 정보"

    def either(data):
        data["tasks"][0]["inputs"] = "로컬 또는 클라우드 PostgreSQL"

    cloud = {"cloud.target": "gcp"}
    assert "deploy.in_first_build" in rules(ServiceDesign(**fields(deploy_task)), cloud)
    assert "deploy.in_first_build" not in rules(ServiceDesign(**fields(either)), cloud)
    assert "deploy.in_first_build" not in rules(ServiceDesign(**fields(deploy_task)), {})


def test_n8n_with_a_queue_is_warned_and_gets_no_queue_container():
    design = with_choices(
        fields(), **{"backend.implementation": "n8n", "backend.execution": "queue"}
    )
    spec = plan_build(design, REGISTRY, "아이디어")

    assert "n8n.own_executions" in {issue.rule_id for issue in spec.issues}
    assert not any(line.startswith("작업 큐와 워커") for line in spec.containers)
    assert "## 확인할 점" in build_package(spec)["BUILD.md"]


def test_design_errors_reach_the_validator_and_warnings_do_not_block():
    constraints = _fixture.constraints(vector_store="none")
    found = validate_design(ServiceDesign(**fields(vector_tool)), constraints)

    assert ("decision.vector_store_not_chosen", "error") in {(i.rule_id, i.severity) for i in found}
    assert all(issue.route == "design" for issue in design_issues(
        ServiceDesign(**fields(vector_tool)), {"data.vector_store": "none"}) if issue.severity == "error")  # fmt: skip


def test_errors_left_in_a_saved_design_become_remaining_decisions():
    design = with_choices(fields(vector_tool), **{"data.vector_store": "none"})
    spec = plan_build(design, REGISTRY, "아이디어")

    questions = [item.question for item in spec.open if item.title == "설계와 결정이 맞지 않는 곳"]
    assert any("벡터 검색" in question for question in questions)


# The three build trials (2026-11-24), rebuilt from their build notes


def test_trial_c1_search_store_and_serving_contradictions_are_caught():
    def c1(data):
        vector_tool(data)
        no_empty_case(data)
        _fixture.by_id(data, "answer")["model"]["provider_scope"] = "upstage"

    chosen = {"data.vector_store": "none", "model.provider": "upstage",
              "mlops.model_serving": "ollama"}  # fmt: skip
    found = rules(ServiceDesign(**fields(c1)), chosen)

    assert {"decision.vector_store_not_chosen", "decision.serving_unused",
            "eval.no_empty_result_case"} <= found  # fmt: skip


def test_trial_c2_reopened_search_store_is_caught():
    def c2(data):
        data["unknowns"] = [{"text": "pgvector를 사용할지 외부 벡터 저장소를 도입할지 결정이 필요합니다",
                             "blocks_confirmation": False}]  # fmt: skip

    assert "decision.vector_store_reopened" in rules(
        ServiceDesign(**fields(c2)), {"data.vector_store": "none"}
    )


def test_trial_c4_login_and_cloud_in_the_first_build_are_caught():
    def c4(data):
        data["tasks"][0]["inputs"] = "PostgreSQL 데이터베이스 및 GCP 워커 환경 설정값"

    design = with_choices(fields(c4), **{"product.surface": "web", "cloud.target": "gcp"})
    found = rules(design, {"product.surface": "web", "cloud.target": "gcp"}, TEAM)
    infra = build_package(plan_build(design, REGISTRY, "아이디어", project=TEAM))[
        "docs/infrastructure.md"
    ]

    assert {"access.many_users_no_login", "deploy.in_first_build"} <= found
    assert "클라우드 계정" not in infra.split("## 배포 (나중)")[0]
