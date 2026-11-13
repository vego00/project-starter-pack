import io
import json
import zipfile
from uuid import uuid4

import pytest
from app.config import Settings
from app.journey.design import ServiceDesign, ValidationIssue
from app.journey.design_constraints import derive_design_constraints
from app.journey.design_generator import (
    MAX_ATTEMPTS,
    MAX_OUTAGE_RETRIES,
    DesignAttempt,
    DesignDraft,
    generate_design,
    score_design,
    template_design,
)
from app.journey.llm import provider_schema
from app.journey.modules import ModuleNote
from app.journey.package import build_package, package_zip
from app.journey.services import JourneyDeps, llm_calls_used
from app.journey.state import (
    MAX_LLM_CALLS_PER_JOURNEY,
    Decision,
    JourneyState,
    NodeEvent,
    ProjectSpec,
)
from app.main import create_app
from app.registry.loader import load_registry
from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

REGISTRY = load_registry()
CHOICES = {
    "agent.topology": "pipeline",
    "agent.hitl": "none",
    "model.provider": "gemini",
    "data.checkpointer": "postgres",
    "backend.execution": "sync",
    "devops.orchestration": "none",
    "mlops.model_serving": "external_api",
    "cloud.target": "gcp",
}
IDEA = "강의 자료를 찾아 답하는 멀티 에이전트 서비스"


def journey(**overrides):
    choices = {**CHOICES, **overrides}
    return JourneyState(
        journey_id=uuid4(),
        project_spec=ProjectSpec(idea=IDEA),
        decisions={
            card_id: Decision(
                card_id=card_id,
                card_version=REGISTRY.card(card_id).version,
                option_id=option,
                by="user",
                at="2026-11-05T00:00:00Z",
            )
            for card_id, option in choices.items()
        },
    )


def node(node_id, kind, inputs, outputs):
    fields = {
        "id": node_id,
        "kind": kind,
        "responsibility": f"{node_id} 역할",
        "inputs": [{"name": n, "type": "str"} for n in inputs],
        "outputs": [{"name": n, "type": "str"} for n in outputs],
        "tools": [],
        "done_when": "끝남",
        "on_failure": "알린다",
    }
    if kind == "agent":
        fields["model"] = {"capability": "답변", "provider_scope": "gemini"}
    return fields


def draft(**overrides):
    fields = {
        "requirements": [
            {
                "id": "R-1",
                "problem": "강의 내용을 찾지 못한다",
                "success_example": "출처와 함께 답한다",
                "input": "질문",
                "expected_output": "출처 있는 답",
                "evidence": "강의 자료를 찾아 답하는",
                "core": True,
                "node_ids": ["search", "answer"],
                "output": "text",
                "eval_case_ids": ["E-1"],
                "task_ids": ["T-1"],
            }
        ],
        "nodes": [
            node("search", "agent", ["question"], ["hits"]),
            node("answer", "agent", ["hits"], ["text"]),
        ],
        "workflow": {
            "entry": "search",
            "exits": ["answer"],
            "edges": [{"source": "search", "target": "answer"}],
            "max_model_calls": 4,
        },
        "eval_cases": [{"id": "E-1", "given": "강의 질문", "expect": "출처가 있다"}],
        "tasks": [
            {"id": "T-1", "title": "검색 노드", "inputs": "질문", "produces": "함수",
             "verify_by": "결과가 나온다"}
        ],
        "reasons": [{"text": "검색과 답변의 컨텍스트가 다르다", "requirement_ids": ["R-1"]}],
    }  # fmt: skip
    return DesignDraft.model_validate({**fields, **overrides})


class ScriptedDesigner:
    def __init__(self, *outputs):
        self.outputs = list(outputs)
        self.problems = []

    def draft(self, state, constraints, problems):
        self.problems.append(problems)
        output = self.outputs.pop(0)
        if isinstance(output, Exception):
            raise output
        return DesignAttempt(draft=output, model_id="test-model", input_tokens=10, output_tokens=5)


def too_few_agents():
    return draft(
        nodes=[node("answer", "agent", ["question"], ["text"])],
        workflow={"entry": "answer", "exits": ["answer"], "edges": [], "max_model_calls": 1},
        requirements=[
            {**draft().requirements[0].model_dump(), "node_ids": ["answer"]},
        ],
    )


def test_a_valid_draft_becomes_a_design_to_review():
    designer = ScriptedDesigner(draft())

    outcome = generate_design(journey(), REGISTRY, designer)

    assert outcome.design.status == "review_required"
    assert outcome.design.current.provenance.source == "model"
    assert outcome.design.current.confirm_blockers == []
    assert outcome.model_id == "test-model"
    assert designer.problems == [[]]


def test_validation_errors_go_back_to_the_model_once():
    designer = ScriptedDesigner(too_few_agents(), draft())

    outcome = generate_design(journey(), REGISTRY, designer)

    assert outcome.design.status == "review_required"
    assert any("에이전트" in problem for problem in designer.problems[1])
    assert any("고치는 법: 권한" in problem for problem in designer.problems[1])
    assert outcome.input_tokens == 20


def test_a_failed_validation_is_logged_by_rule_without_its_message(caplog):
    generate_design(journey(), REGISTRY, ScriptedDesigner(too_few_agents(), draft()))

    assert "rules=['decision.too_few_agents']" in caplog.text
    assert "에이전트가" not in caplog.text


# Several candidates (Graph of Thoughts: Generate k, Score, KeepBest)


def no_call_limit():
    """Valid but with one warning: no model call limit."""
    workflow = {**draft().workflow.model_dump(), "max_model_calls": None}
    return draft(workflow=workflow)


def test_candidates_are_drafted_from_scratch_and_the_best_is_kept():
    designer = ScriptedDesigner(too_few_agents(), no_call_limit(), draft())

    outcome = generate_design(journey(), REGISTRY, designer, attempts=3, candidates=3)

    assert designer.problems == [[], [], []]
    assert outcome.design.status == "review_required"
    assert outcome.design.current.workflow.max_model_calls == 4  # fewer warnings won


def test_a_draft_that_broke_the_contract_is_not_a_candidate():
    designer = ScriptedDesigner(contract_error(), too_few_agents(), no_call_limit())

    outcome = generate_design(journey(), REGISTRY, designer, attempts=3, candidates=3)

    assert outcome.design.status == "review_required"
    assert outcome.design.current.workflow.max_model_calls is None


def test_when_every_candidate_is_broken_the_best_one_is_corrected():
    designer = ScriptedDesigner(too_few_agents(), contract_error(), draft())

    outcome = generate_design(journey(), REGISTRY, designer, attempts=3, candidates=2)

    assert designer.problems[:2] == [[], []]
    assert any("에이전트" in problem for problem in designer.problems[2])
    assert outcome.design.status == "review_required"


def test_candidates_never_exceed_the_attempts():
    designer = ScriptedDesigner(too_few_agents(), too_few_agents())

    outcome = generate_design(journey(), REGISTRY, designer, attempts=2, candidates=5)

    assert len(designer.problems) == 2
    assert outcome.design.current.provenance.source == "template"


def contract_error():
    fields = draft().model_dump()
    fields["state_fields"] = [
        {"name": "secret-idea", "type": "str", "writers": [], "readers": [], "lifetime": "run"}
    ]
    try:
        DesignDraft.model_validate(fields)
    except ValidationError as exc:
        return exc
    raise AssertionError("the draft should break the contract")


def test_a_broken_contract_tells_the_model_which_field_to_fix():
    designer = ScriptedDesigner(contract_error(), draft())

    outcome = generate_design(journey(), REGISTRY, designer)

    assert outcome.design.status == "review_required"
    assert "state_fields.0.writers" in designer.problems[1][0]
    assert "고치는 법" in designer.problems[1][0]
    assert "secret-idea" not in " ".join(designer.problems[1])


def test_a_broken_contract_is_logged_by_field_without_its_content(caplog):
    generate_design(journey(), REGISTRY, ScriptedDesigner(contract_error(), draft()))

    assert "state_fields.0.writers:too_short" in caplog.text
    assert "secret-idea" not in caplog.text


def test_a_provider_failure_is_logged_with_its_status_without_its_message(caplog):
    outage = RuntimeError("secret input")
    outage.code = 503

    generate_design(journey(), REGISTRY, ScriptedDesigner(outage, draft()))

    assert "status=503" in caplog.text
    assert "secret" not in caplog.text


def test_a_provider_failure_keeps_the_correction_for_a_broken_draft():
    designer = ScriptedDesigner(RuntimeError("down"), contract_error(), draft())

    outcome = generate_design(journey(), REGISTRY, designer)

    assert outcome.design.status == "review_required"
    assert designer.problems[1] == []
    assert "state_fields.0.writers" in designer.problems[2][0]


def test_a_provider_failure_keeps_the_problems_still_to_fix():
    designer = ScriptedDesigner(too_few_agents(), RuntimeError("down"), draft())

    outcome = generate_design(journey(), REGISTRY, designer)

    assert outcome.design.status == "review_required"
    assert designer.problems[2] == designer.problems[1] != []


def test_without_spare_budget_a_provider_failure_uses_up_an_attempt():
    designer = ScriptedDesigner(RuntimeError("down"), RuntimeError("down"))

    outcome = generate_design(journey(), REGISTRY, designer, attempts=2, outage_retries=0)

    assert len(designer.problems) == 2
    assert outcome.design.status == "failed"


@pytest.mark.parametrize(
    ("outputs", "calls"),
    [
        ([too_few_agents(), too_few_agents()], MAX_ATTEMPTS),
        ([RuntimeError("timeout")] * (MAX_ATTEMPTS + MAX_OUTAGE_RETRIES), MAX_ATTEMPTS + 1),
    ],
)
def test_repeated_failure_falls_back_to_a_template_that_cannot_be_confirmed(outputs, calls):
    designer = ScriptedDesigner(*outputs)

    outcome = generate_design(journey(), REGISTRY, designer)

    assert len(designer.problems) == calls
    assert outcome.design.status == "failed"
    assert outcome.design.error
    assert outcome.design.current.provenance.source == "template"
    assert "source_not_model" in outcome.design.current.confirm_blockers


def test_without_a_model_the_template_is_used():
    outcome = generate_design(journey(), REGISTRY, None)

    assert outcome.design.status == "failed"
    assert outcome.prompt_version is None


def test_no_budget_means_no_model_call():
    designer = ScriptedDesigner()

    outcome = generate_design(journey(), REGISTRY, designer, attempts=0)

    assert designer.problems == []
    assert outcome.design.current.provenance.source == "template"


@pytest.mark.parametrize("topology", ["single", "pipeline", "supervisor", "hierarchical"])
@pytest.mark.parametrize("hitl", ["none", "question", "approval"])
def test_the_template_obeys_every_decision(topology, hitl):
    state = journey(**{"agent.topology": topology, "agent.hitl": hitl})
    design = template_design(state, derive_design_constraints(state, REGISTRY))

    assert design.validation == []


def test_a_deferred_card_stays_visible_even_if_the_model_ignores_it():
    state = journey()
    del state.decisions["agent.hitl"]

    design = generate_design(state, REGISTRY, ScriptedDesigner(draft())).design.current

    assert any(unknown.blocks_confirmation for unknown in design.unknowns)
    assert "blocking_unknowns" in design.confirm_blockers


def test_the_designer_counts_toward_the_model_call_budget():
    state = journey()
    state.trace = [NodeEvent(node="designer", latency_ms=1, model_id="m")]

    assert llm_calls_used(state) == 1
    assert MAX_LLM_CALLS_PER_JOURNEY > MAX_ATTEMPTS


# Package


@pytest.fixture
def design() -> ServiceDesign:
    return generate_design(journey(), REGISTRY, ScriptedDesigner(draft())).design.current


def with_issues(design: ServiceDesign, *severities: str) -> ServiceDesign:
    issues = [ValidationIssue(rule_id="r", severity=s, message="m") for s in severities]
    return design.model_copy(update={"validation": issues})


def test_a_broken_rule_outweighs_any_number_of_warnings(design):
    one_error = with_issues(design, "error")
    many_warnings = with_issues(design, *["warning"] * 5)

    assert score_design(many_warnings) < score_design(one_error)
    assert score_design(with_issues(design)) == (0, 0)


def test_the_same_design_always_gets_the_same_score(design):
    assert score_design(design) == score_design(design.model_copy())


def test_the_package_has_files_for_both_kinds_of_agent(design):
    files = build_package(design, REGISTRY, IDEA)

    assert {
        "BUILD.md",
        "CLAUDE.md",
        "AGENTS.md",
        ".claude/settings.json",
        ".claude/skills/build-service/SKILL.md",
        ".claude/skills/verify-design/SKILL.md",
        "agents/search.md",
        "agents/answer.md",
        "docs/multi-agent-design.md",
        "docs/infrastructure.md",
        "docs/lessons.md",
        "docs/gates.md",
    } == set(files)


def test_the_build_order_lists_modules_with_their_start_conditions(design):
    files = build_package(design, REGISTRY, IDEA)
    build = files["BUILD.md"]

    order = [build.index(f"단계: {name}") for name in ("에이전트 흐름", "서비스 API", "운영")]
    assert order == sorted(order)
    assert "## 만드는 순서" in build
    assert "핵심 요구사항마다 평가 사례를 먼저 쓰고" in build
    assert "답변 응답 시간: 목표치를 시작 전에 사용자에게 묻는다" in build
    assert "docs/gates.md" in files["CLAUDE.md"]


def test_every_start_condition_gets_a_line_to_record_it(design):
    files = build_package(design, REGISTRY, IDEA)

    gates = files["docs/gates.md"]
    for line in files["BUILD.md"].splitlines():
        if line.startswith("- ") and "(이유: " in line:
            assert f"- [ ] {line[2 : line.index(' (이유: ')]}" in gates
    assert "정할 값: 답변 응답 시간 목표치:" in gates


def test_what_people_said_about_a_module_reaches_the_package(design):
    notes = {
        "agent": ModuleNote(
            goal="강의 자료로 답한다",
            include=["근거 표시"],
            exclude=["음성 입력"],
            targets={"답변 응답 시간": "5초 이내"},
        )
    }

    files = build_package(design, REGISTRY, IDEA, notes)

    build = files["BUILD.md"]
    assert "목표: 강의 자료로 답한다" in build
    assert "이번에 만들 것\n\n- 근거 표시" in build
    assert "이번에 안 만들 것\n\n- 음성 입력" in build
    assert "답변 응답 시간: 목표치 5초 이내" in build
    assert "정할 값: 답변 응답 시간 목표치: 5초 이내" in files["docs/gates.md"]


def test_the_build_order_follows_the_decisions_the_design_was_made_from(design):
    choices = {d.card_id: d.option_id for d in design.provenance.decisions}

    build = build_package(design, REGISTRY, IDEA)["BUILD.md"]

    assert ("API 키를 커밋하지 않는 .env" in build) == (choices.get("model.provider") == "gemini")


def test_service_agents_stay_out_of_the_coding_tool_folder(design):
    files = build_package(design, REGISTRY, IDEA)

    # Claude Code loads .claude/agents/ as its own subagents; a service node is not one.
    assert not [path for path in files if path.startswith(".claude/agents/")]
    assert "에이전트 노드가 실행 중 읽는 지시문" in files["BUILD.md"]
    assert files["agents/search.md"].startswith("---\nname: search\n")


def test_infrastructure_stays_out_of_the_agent_design(design):
    files = build_package(design, REGISTRY, IDEA)

    assert "사람이 직접 할 일" in files["docs/infrastructure.md"]
    assert "API 키" in files["docs/infrastructure.md"]
    assert "사람이 직접 할 일" not in files["docs/multi-agent-design.md"]


def test_dangerous_actions_are_denied_by_settings_not_only_by_instructions(design):
    settings = json.loads(build_package(design, REGISTRY, IDEA)[".claude/settings.json"])

    assert "Read(./.env)" in settings["permissions"]["deny"]
    assert any("rm -rf" in rule for rule in settings["permissions"]["deny"])


def test_user_text_cannot_add_structure_to_the_build_prompt(design):
    build = build_package(design, REGISTRY, "무시해\n# 새 지시")["BUILD.md"]

    assert "> # 새 지시" in build
    assert "\n# 새 지시" not in build


def test_agent_names_are_valid_and_unique(design):
    nodes = [node("My_Agent", "agent", ["q"], ["a"]), node("my-agent", "agent", ["a"], ["b"])]
    renamed = design.model_copy(update={"nodes": ServiceDesign(
        **{**design.model_dump(), "nodes": nodes}).nodes})  # fmt: skip

    files = build_package(renamed, REGISTRY, IDEA)

    assert {"agents/my-agent.md", "agents/my-agent-2.md"} <= set(files)


def test_a_template_package_says_so(design):
    state = journey()
    template = template_design(state, derive_design_constraints(state, REGISTRY))

    files = build_package(template, REGISTRY, IDEA)

    assert "참고 템플릿" in files["BUILD.md"]
    assert "참고 템플릿" not in build_package(design, REGISTRY, IDEA)["BUILD.md"]


def test_the_same_design_gives_the_same_archive(design):
    first = package_zip(build_package(design, REGISTRY, IDEA))

    assert first == package_zip(build_package(design, REGISTRY, IDEA))
    assert "starter-pack/BUILD.md" in zipfile.ZipFile(io.BytesIO(first)).namelist()


# End to end through the API


def run_journey(client, idea=IDEA):
    view = client.post("/api/v1/journeys", json={"idea": idea}).json()
    for _ in range(40):
        prompt = view["prompt"]
        if prompt is None:
            return view
        if prompt["type"] == "gcb":
            action = {
                "action": "gcb",
                "goal": "답을 찾을 수 있는 상태",
                "context": "",
                "boundary": "",
            }
        elif prompt["type"] == "clarify":
            action = {"action": "clarify", "answers": {}}
        elif prompt["type"] == "fork":
            action = {"action": "plan_deploy"}
        else:
            action = {"action": "accept_recommendation"}
        before = view
        response = client.post(
            f"/api/v1/journeys/{view['journey_id']}/decisions",
            json={"revision": view["revision"], "action": action},
        )
        assert response.status_code == 200, (before["prompt"]["type"], response.text)
        view = response.json()
    raise AssertionError("journey did not finish")


def make_client(designer=None):
    settings = Settings(_env_file=None, provider="mock", decider="mock")
    app = create_app(
        settings,
        checkpointer=InMemorySaver(),
        deps=JourneyDeps(designer=designer),
        registry=REGISTRY,
    )
    return TestClient(app)


def test_pain_point_to_downloadable_package():
    with make_client(ScriptedDesigner(draft())) as client:
        view = run_journey(client)
        archive = client.get(f"/api/v1/journeys/{view['journey_id']}/package.zip")

    assert view["status"] == "completed"
    assert view["design"]["status"] == "review_required"
    assert view["design"]["source"] == "model"
    assert [n["id"] for n in view["design"]["nodes"]] == ["search", "answer"]
    assert archive.status_code == 200
    assert archive.headers["content-type"] == "application/zip"
    names = zipfile.ZipFile(io.BytesIO(archive.content)).namelist()
    assert "starter-pack/BUILD.md" in names


def test_without_a_model_the_journey_still_ends_with_a_labelled_template():
    with make_client() as client:
        view = run_journey(client)

    assert view["design"]["source"] == "template"
    assert view["design"]["error"]


def test_a_model_failure_never_fails_the_journey():
    outages = [RuntimeError("down")] * (MAX_ATTEMPTS + MAX_OUTAGE_RETRIES)
    with make_client(ScriptedDesigner(*outages)) as client:
        view = run_journey(client)

    assert view["status"] == "completed"
    assert view["design"]["status"] == "failed"
    assert view["cards"]


def test_the_full_design_is_readable_after_the_journey():
    with make_client(ScriptedDesigner(draft())) as client:
        view = run_journey(client)
        response = client.get(f"/api/v1/journeys/{view['journey_id']}/design")

    assert response.status_code == 200
    design = ServiceDesign.model_validate(response.json())
    assert [n.id for n in design.nodes] == ["search", "answer"]
    assert design.workflow.edges


def reopen(client, view, card_id):
    return client.post(
        f"/api/v1/journeys/{view['journey_id']}/decisions",
        json={"revision": view["revision"], "action": {"action": "reopen", "card_id": card_id}},
    )


def test_a_finished_journey_can_change_one_decision_and_redesign():
    with make_client() as client:
        finished = run_journey(client)
        assert finished["can_reopen"] is True
        first = client.get(f"/api/v1/journeys/{finished['journey_id']}/design").json()

        reopened = reopen(client, finished, "model.provider").json()
        assert reopened["status"] == "in_progress"
        assert reopened["can_reopen"] is False
        assert reopened["prompt"]["card"]["card_id"] == "model.provider"

        view = client.post(
            f"/api/v1/journeys/{finished['journey_id']}/decisions",
            json={
                "revision": reopened["revision"],
                "action": {"action": "select", "option_id": "openai"},
            },
        ).json()
        while view["prompt"]:  # Only cards the change affected are asked again.
            assert view["prompt"]["type"] == "decision"
            view = client.post(
                f"/api/v1/journeys/{view['journey_id']}/decisions",
                json={"revision": view["revision"], "action": {"action": "accept_recommendation"}},
            ).json()
        second = client.get(f"/api/v1/journeys/{finished['journey_id']}/design").json()

    assert view["status"] == "completed" and view["can_reopen"] is True
    providers = {d["card_id"]: d["option_id"] for d in second["provenance"]["decisions"]}
    assert providers["model.provider"] == "openai"
    assert (first["design_revision"], second["design_revision"]) == (1, 2)
    others = {c["card_id"]: c["option_name"] for c in finished["cards"]}
    assert {
        c["card_id"]: c["option_name"] for c in view["cards"] if c["card_id"] != "model.provider"
    } == {k: v for k, v in others.items() if k != "model.provider"}


def test_reopen_after_finishing_rejects_a_card_that_was_never_decided():
    with make_client() as client:
        finished = run_journey(client)
        response = reopen(client, finished, "no.such.card")
        after = client.get(f"/api/v1/journeys/{finished['journey_id']}").json()

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "reopen_rejected"
    assert after["revision"] == finished["revision"]


def test_a_finished_journey_still_rejects_other_actions():
    with make_client() as client:
        finished = run_journey(client)
        response = client.post(
            f"/api/v1/journeys/{finished['journey_id']}/decisions",
            json={"revision": finished["revision"], "action": {"action": "defer"}},
        )

    assert response.json()["error"]["code"] == "journey_finished"


def test_no_design_before_the_journey_ends():
    with make_client() as client:
        view = client.post("/api/v1/journeys", json={"idea": IDEA}).json()
        response = client.get(f"/api/v1/journeys/{view['journey_id']}/design")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "design_unavailable"


def test_no_package_before_the_journey_ends():
    with make_client() as client:
        view = client.post("/api/v1/journeys", json={"idea": IDEA}).json()
        response = client.get(f"/api/v1/journeys/{view['journey_id']}/package.zip")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "package_unavailable"


def test_the_schema_sent_to_the_model_drops_only_what_the_provider_rejects():
    schema = provider_schema(DesignDraft.model_json_schema())
    text = json.dumps(schema)

    for keyword in ('"pattern"', '"maxItems"', '"minLength"', '"discriminator"', '"oneOf"'):
        assert keyword not in text
    assert {"requirements", "nodes", "workflow", "tasks"} <= set(schema["properties"])
    assert "AgentNode" in schema["$defs"]


def test_a_field_named_like_a_keyword_survives():
    schema = {
        "properties": {"pattern": {"type": "string", "pattern": "^a"}},
        "required": ["pattern"],
    }

    assert provider_schema(schema) == {
        "properties": {"pattern": {"type": "string"}},
        "required": ["pattern"],
    }
