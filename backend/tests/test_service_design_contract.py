import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.journey.design import (
    SCHEMA_VERSION,
    ChangeRequest,
    Confirmation,
    DecisionRef,
    DesignState,
    Provenance,
    Requirement,
    ServiceDesign,
    StateField,
    Unknown,
    ValidationIssue,
)
from app.journey.graph import build_graph, journey_config, journey_input
from app.journey.nodes import resume_command
from app.journey.state import JourneyState, ProjectSpec
from app.registry.loader import load_registry
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import ValidationError

NOW = datetime(2026, 11, 5, tzinfo=UTC)
# Journey states saved by the code before the design field existed (commit 9ac78b0).
OLD_STATES = json.loads(
    (Path(__file__).parent / "fixtures" / "journey_state_before_design.json").read_text("utf-8")
)


def provenance(**overrides):
    fields = {
        "journey_revision": 12,
        "project_spec_hash": "a" * 64,
        "decisions": [
            {"card_id": "agent.topology", "card_version": 1, "option_id": "single", "by": "user"},
            {"card_id": "agent.hitl", "card_version": 1, "by": "deferred"},
        ],
        "generated_at": NOW,
        "source": "model",
        "model_id": "test-model",
        "prompt_version": "design-v1",
    }
    return {**fields, **overrides}


def requirement(**overrides):
    fields = {
        "id": "R-1",
        "problem": "수강생이 강의 내용을 찾지 못한다",
        "success_example": "질문하면 출처와 함께 답한다",
        "input": "질문",
        "expected_output": "출처가 붙은 답",
        "evidence": "강의 자료를 찾아 답하는",
        "core": True,
        "node_ids": ["answer"],
        "output": "answer_text",
        "eval_case_ids": ["E-1"],
        "task_ids": ["T-1"],
    }
    return {**fields, **overrides}


def agent_node(**overrides):
    fields = {
        "id": "answer",
        "kind": "agent",
        "responsibility": "질문에 답한다",
        "inputs": [{"name": "question", "type": "str"}],
        "outputs": [{"name": "answer_text", "type": "str"}],
        "tools": [],
        "done_when": "출처가 붙은 답을 만들었다",
        "on_failure": "모른다고 답한다",
        "model": {"capability": "한국어 답변", "provider_scope": "선택한 API"},
    }
    return {**fields, **overrides}


def design(**overrides):
    fields = {
        "design_revision": 1,
        "provenance": provenance(),
        "requirements": [requirement()],
        "nodes": [agent_node()],
        "workflow": {"entry": "answer", "exits": ["answer"], "edges": []},
        "eval_cases": [{"id": "E-1", "given": "강의 질문", "expect": "출처가 있다"}],
        "tasks": [
            {
                "id": "T-1",
                "title": "답변 노드 만들기",
                "inputs": "예시 질문",
                "produces": "답변 함수",
                "verify_by": "예시 질문에 출처가 붙는다",
            }
        ],
        "reasons": [{"text": "역할이 하나라 Single Agent로 충분하다", "requirement_ids": ["R-1"]}],
        "validation": [],
    }
    return {**fields, **overrides}


CONFIRMED = Confirmation(design_revision=1, at=NOW).model_dump()


def test_a_full_design_survives_the_json_a_checkpoint_stores():
    original = ServiceDesign(**design(confirmation=CONFIRMED))

    restored = ServiceDesign.model_validate(json.loads(original.model_dump_json()))

    assert restored == original
    assert restored.schema_version == SCHEMA_VERSION
    assert restored.nodes[0].model.capability == "한국어 답변"


def test_the_schema_can_be_exported_for_a_model_and_the_screen():
    schema = ServiceDesign.model_json_schema()

    assert {"requirements", "nodes", "workflow", "tasks"} <= set(schema["properties"])


@pytest.mark.parametrize(
    "overrides",
    [
        {"requirements": []},
        {"nodes": []},
        {"tasks": []},
        {"eval_cases": []},
        {"reasons": []},
        {"unexpected": 1},
        {"schema_version": 2},
        {"design_revision": 0},
    ],
)
def test_a_design_rejects_missing_parts_and_unknown_shapes(overrides):
    with pytest.raises(ValidationError):
        ServiceDesign(**design(**overrides))


def test_a_design_cannot_be_changed_in_place():
    with pytest.raises(ValidationError):
        ServiceDesign(**design()).design_revision = 2


# Requirement trace


@pytest.mark.parametrize("missing", ["node_ids", "eval_case_ids", "task_ids"])
def test_a_core_requirement_must_be_traced_end_to_end(missing):
    with pytest.raises(ValidationError):
        Requirement(**requirement(**{missing: []}))


def test_a_core_requirement_must_name_its_output():
    with pytest.raises(ValidationError):
        Requirement(**requirement(output=None))


def test_a_supporting_requirement_may_stay_untraced():
    fields = requirement(core=False, node_ids=[], output=None, eval_case_ids=[], task_ids=[])

    assert Requirement(**fields).core is False


def test_a_requirement_without_evidence_is_an_assumption():
    assert Requirement(**requirement()).is_assumption is False
    assert Requirement(**requirement(evidence=None)).is_assumption is True


@pytest.mark.parametrize("bad_id", ["1R", "R 1", "", "R" * 65])
def test_ids_stay_stable_and_simple(bad_id):
    with pytest.raises(ValidationError):
        Requirement(**requirement(id=bad_id))


# Node kinds


def test_only_an_agent_node_has_a_model():
    assert ServiceDesign(**design()).nodes[0].kind == "agent"

    for kind in ("code", "human"):
        with pytest.raises(ValidationError):
            ServiceDesign(**design(nodes=[agent_node(kind=kind)]))


def test_an_agent_node_must_state_its_model_need():
    fields = agent_node()
    del fields["model"]

    with pytest.raises(ValidationError):
        ServiceDesign(**design(nodes=[fields]))


def test_a_code_node_needs_no_model():
    fields = agent_node(kind="code")
    del fields["model"]

    assert ServiceDesign(**design(nodes=[fields])).nodes[0].kind == "code"


def test_tool_permissions_must_be_stated_even_when_there_are_none():
    fields = agent_node()
    del fields["tools"]

    with pytest.raises(ValidationError):
        ServiceDesign(**design(nodes=[fields]))


def test_an_unknown_node_kind_is_rejected():
    with pytest.raises(ValidationError):
        ServiceDesign(**design(nodes=[agent_node(kind="supervisor")]))


def test_several_writers_must_state_how_they_merge():
    fields = {"name": "notes", "type": "list", "readers": [], "lifetime": "run"}

    assert StateField(**fields, writers=["a"]).merge is None
    assert StateField(**fields, writers=["a", "b"], merge="append").merge == "append"
    with pytest.raises(ValidationError):
        StateField(**fields, writers=["a", "b"])


# Provenance


def test_a_model_design_must_name_its_model_and_prompt():
    for missing in ("model_id", "prompt_version"):
        with pytest.raises(ValidationError):
            Provenance(**provenance(**{missing: None}))


@pytest.mark.parametrize("source", ["mock", "template"])
def test_a_design_without_a_model_must_not_name_one(source):
    with pytest.raises(ValidationError):
        Provenance(**provenance(source=source))

    assert Provenance(**provenance(source=source, model_id=None, prompt_version=None))


def test_the_spec_is_stored_as_a_hash_not_as_text():
    with pytest.raises(ValidationError):
        Provenance(**provenance(project_spec_hash="수강생이 강의 내용을 찾지 못한다"))


def test_only_a_deferred_decision_has_no_option():
    base = {"card_id": "a.b", "card_version": 1}

    with pytest.raises(ValidationError):
        DecisionRef(**base, by="deferred", option_id="x")
    with pytest.raises(ValidationError):
        DecisionRef(**base, by="user")


# Confirmation


@pytest.mark.parametrize("source", ["mock", "template"])
def test_mock_and_template_designs_can_never_be_confirmed(source):
    fields = design(
        provenance=provenance(source=source, model_id=None, prompt_version=None),
    )
    assert ServiceDesign(**fields).confirm_blockers == ["source_not_model"]

    with pytest.raises(ValidationError, match="source_not_model"):
        ServiceDesign(**fields, confirmation=CONFIRMED)


def test_a_design_that_was_not_validated_cannot_be_confirmed():
    fields = design(validation=None)
    assert ServiceDesign(**fields).confirm_blockers == ["not_validated"]

    with pytest.raises(ValidationError, match="not_validated"):
        ServiceDesign(**fields, confirmation=CONFIRMED)


def test_a_validation_error_blocks_confirmation_and_a_warning_does_not():
    def issue(severity):
        return ValidationIssue(rule_id="r", severity=severity, message="m").model_dump()

    assert ServiceDesign(**design(validation=[issue("warning")], confirmation=CONFIRMED))

    with pytest.raises(ValidationError, match="validation_errors"):
        ServiceDesign(**design(validation=[issue("error")], confirmation=CONFIRMED))


def test_only_a_blocking_unknown_stops_confirmation():
    blocking = Unknown(text="외부 쓰기 권한이 필요한지 모른다", blocks_confirmation=True)
    minor = Unknown(text="화면 문구를 정하지 않았다", blocks_confirmation=False)

    assert ServiceDesign(**design(unknowns=[minor.model_dump()], confirmation=CONFIRMED))
    with pytest.raises(ValidationError, match="blocking_unknowns"):
        ServiceDesign(**design(unknowns=[blocking.model_dump()], confirmation=CONFIRMED))


def test_a_confirmation_does_not_carry_over_to_a_new_revision():
    with pytest.raises(ValidationError, match="revision"):
        ServiceDesign(**design(design_revision=2, confirmation=CONFIRMED))


def test_a_change_request_must_move_the_revision_forward():
    fields = {"request": "역할을 줄여 주세요", "summary": "노드 하나를 합쳤어요"}

    assert ChangeRequest(from_revision=1, to_revision=2, **fields)
    with pytest.raises(ValidationError):
        ChangeRequest(from_revision=2, to_revision=2, **fields)


# Design status, kept apart from the journey's own status


def test_design_status_starts_empty():
    state = DesignState()

    assert (state.status, state.current) == ("not_started", None)


@pytest.mark.parametrize(
    ("status", "current"),
    [
        ("not_started", design()),
        ("review_required", None),
        ("review_required", design(confirmation=CONFIRMED)),
        ("confirmed", None),
        ("confirmed", design()),
    ],
)
def test_design_status_must_match_its_design(status, current):
    with pytest.raises(ValidationError):
        DesignState(status=status, current=current)


@pytest.mark.parametrize(
    ("status", "current"),
    [
        ("generating", None),
        ("generating", design(confirmation=CONFIRMED)),
        ("review_required", design()),
        ("confirmed", design(confirmation=CONFIRMED)),
        ("failed", None),
    ],
)
def test_valid_design_statuses(status, current):
    assert DesignState(status=status, current=current).status == status


def test_a_failed_run_keeps_the_last_good_design():
    confirmed = ServiceDesign(**design(confirmation=CONFIRMED))

    state = DesignState(status="failed", current=confirmed, error="model_timeout")

    assert state.current == confirmed


def test_history_only_holds_confirmed_designs():
    with pytest.raises(ValidationError):
        DesignState(confirmed_history=[design()])

    assert DesignState(confirmed_history=[design(confirmation=CONFIRMED)])


# Journeys saved before the design field existed


@pytest.mark.parametrize("saved", ["in_progress", "completed"])
def test_a_journey_saved_before_the_design_field_still_loads(saved):
    values = OLD_STATES[saved]
    assert "design" not in values

    state = JourneyState.model_validate(values)

    assert state.design == DesignState()
    assert state.decisions.keys() == values["decisions"].keys()


def test_a_completed_old_journey_keeps_its_own_status_and_summary():
    state = JourneyState.model_validate(OLD_STATES["completed"])

    assert state.status == "completed"
    assert state.design.status == "not_started"
    assert "decision_summary" in state.artifacts


def test_a_finished_journey_saves_its_design_in_a_shape_that_loads_again():
    """The graph must not add the channel: a checkpoint then looks just like an old one."""
    saver = InMemorySaver()
    graph = build_graph(load_registry(), checkpointer=saver)
    journey_id = uuid4()
    config = journey_config(journey_id)
    spec = ProjectSpec(
        idea="강의 자료를 찾아 답하는 멀티 에이전트 서비스",
        goal="수강생이 근거와 함께 답을 찾을 수 있는 상태",
        team_size=4,
        duration_weeks=8,
        budget="월 5만원",
        expected_users=20,
        weekly_hours=20,
        data_traits=["문서 검색"],
        deployment_target="small_group",
        has_gpu=False,
    )

    result = graph.invoke(journey_input(journey_id, spec), config)
    while (interrupts := result["__interrupt__"])[0].value["type"] != "done":
        card = interrupts[0].value["card"]
        action = {"action": "select", "option_id": card["recommendation"]["option_id"]}
        result = graph.invoke(resume_command(action), config)

    saved = graph.get_state(config).values
    assert saved["status"] == "completed"
    assert JourneyState.model_validate(saved).design.status == "failed"
