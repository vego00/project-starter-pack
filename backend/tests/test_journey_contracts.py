from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.journey.state import GATE_ACTION, Decision, JourneyState, ProjectSpec
from pydantic import ValidationError

IDEA = "강의 자료를 찾아 답하는 멀티 에이전트 서비스"


def test_project_spec_reports_only_unanswered_signals():
    spec = ProjectSpec(idea=IDEA, team_size=4, deployment_target="small_group")

    missing = spec.missing_signals()

    assert "team_size" not in missing and "deployment_target" not in missing
    assert missing[0] == "has_gpu"


def test_no_gpu_is_an_answer_not_a_missing_signal():
    assert "has_gpu" not in ProjectSpec(idea=IDEA, has_gpu=False).missing_signals()


@pytest.mark.parametrize(
    "fields",
    [
        {"idea": "짧음"},
        {"idea": IDEA, "team_size": 0},
        {"idea": IDEA, "deployment_target": "mars"},
        {"idea": IDEA, "unknown": 1},
    ],
)
def test_project_spec_rejects_invalid_input(fields):
    with pytest.raises(ValidationError):
        ProjectSpec(**fields)


def test_decision_records_who_decided():
    with pytest.raises(ValidationError):
        Decision(card_id="a.b", card_version=1, option_id="x", by="llm", at=datetime.now(UTC))


def test_state_survives_a_json_round_trip():
    state = JourneyState(journey_id=uuid4(), project_spec=ProjectSpec(idea=IDEA))

    assert JourneyState.model_validate(state.model_dump(mode="json")) == state


@pytest.mark.parametrize(
    "raw",
    [
        {"action": "select"},
        {"action": "ask", "question": "   "},
        {"action": "decide_for_me"},
        {"action": "defer", "extra": 1},
    ],
)
def test_gate_action_rejects_malformed_input(raw):
    with pytest.raises(ValidationError):
        GATE_ACTION.validate_python(raw)
