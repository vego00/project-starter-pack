import json
from uuid import uuid4

import pytest
from app.journey.deciders.base import DeciderResult
from app.journey.deciders.mock import MockDecider
from app.journey.graph import OwnershipError, _guarded, build_graph, journey_config, journey_input
from app.journey.nodes import resume_command
from app.journey.services import JourneyDeps
from app.journey.state import MAX_QUESTIONS_PER_CARD, JourneyState, ProjectSpec
from app.registry.loader import load_registry
from langgraph.checkpoint.memory import InMemorySaver

REGISTRY = load_registry()
IDEA = "민감한고객문의내용을 처리하는 멀티 에이전트 서비스"
COMPLETE_SPEC = {
    "idea": IDEA,
    "team_size": 4,
    "duration_weeks": 8,
    "budget": "월 5만원",
    "expected_users": 20,
    "weekly_hours": 20,
    "data_traits": ["문서 검색"],
    "deployment_target": "small_group",
}


class Journey:
    """Drives a journey the way an API would: start once, then answer each interrupt."""

    def __init__(self, spec=None, deps=None, checkpointer=None):
        self.id = uuid4()
        self.saver = checkpointer or InMemorySaver()
        self.graph = build_graph(REGISTRY, checkpointer=self.saver, deps=deps)
        self.config = journey_config(self.id)
        project = ProjectSpec(**(spec or COMPLETE_SPEC))
        self.result = self.graph.invoke(journey_input(self.id, project), self.config)

    @property
    def prompt(self):
        interrupts = self.result.get("__interrupt__")
        return interrupts[0].value if interrupts else None

    @property
    def card_id(self):
        return self.prompt["card"]["card_id"]

    @property
    def state(self) -> JourneyState:
        return JourneyState.model_validate(self.graph.get_state(self.config).values)

    def send(self, payload):
        self.result = self.graph.invoke(resume_command(payload), self.config)
        return self

    def select(self, option_id):
        return self.send({"action": "select", "option_id": option_id})

    def choose_defaults(self):
        while self.prompt:
            self.select(self.prompt["card"]["recommendation"]["option_id"])
        return self


def test_full_journey_completes_with_all_seven_user_decisions():
    journey = Journey().choose_defaults()

    state = journey.state
    assert journey.prompt is None
    assert state.status == "completed"
    assert set(state.decisions) == set(REGISTRY.card_ids)
    assert {d.by for d in state.decisions.values()} == {"user"}
    assert state.pending_cards == []


def test_cards_arrive_in_layer_order_with_preparation_merged():
    journey = Journey()
    seen = []
    while journey.prompt:
        card = journey.prompt["card"]
        seen.append(card["card_id"])
        assert card["recommendation"]["decider"] == "mock"
        assert card["advice_source"] == "mock"
        assert card["evidence"] == []
        assert all(view["note"] for view in card["options"])
        journey.send({"action": "accept_recommendation"})

    assert seen == list(REGISTRY.card_ids)


def test_accepting_a_recommendation_is_recorded_as_such():
    state = Journey().send({"action": "accept_recommendation"}).state

    decision = state.decisions["agent.hitl"]
    assert decision.by == "recommended"
    assert decision.option_id == "none"
    assert decision.card_version == 1
    assert decision.rationale


def test_user_rationale_is_kept():
    journey = Journey().send(
        {"action": "select", "option_id": "approval", "rationale": "외부 쓰기"}
    )

    assert journey.state.decisions["agent.hitl"].rationale == "외부 쓰기"


# Clarify Gate
def test_complete_spec_skips_clarify():
    assert Journey().prompt["type"] == "decision"


def test_missing_signals_are_asked_at_most_three_per_round():
    journey = Journey({"idea": IDEA})

    assert journey.prompt["type"] == "clarify"
    assert journey.prompt["round"] == 1
    assert [q["field"] for q in journey.prompt["questions"]] == [
        "deployment_target",
        "expected_users",
        "budget",
    ]


def test_clarify_answers_update_spec_and_are_not_asked_again():
    journey = Journey({"idea": IDEA})
    journey.send({"deployment_target": "local_demo", "expected_users": 3, "budget": "없음"})

    assert journey.state.project_spec.deployment_target == "local_demo"
    assert [q["field"] for q in journey.prompt["questions"]] == [
        "team_size",
        "duration_weeks",
        "weekly_hours",
    ]


def test_clarify_stops_after_two_rounds_even_if_unanswered():
    journey = Journey({"idea": IDEA})
    journey.send({})
    assert journey.prompt["round"] == 2
    journey.send({})

    assert journey.prompt["type"] == "decision"
    assert journey.state.clarify_rounds == 2


@pytest.mark.parametrize("payload", ["모름", None, ["x"], {}])
def test_clarify_tolerates_non_object_answers(payload):
    journey = Journey({"idea": IDEA}).send(payload)

    assert journey.prompt["round"] == 2


def test_invalid_clarify_answer_is_dropped_and_asked_again():
    journey = Journey({"idea": IDEA})
    journey.send({"deployment_target": "mars", "expected_users": -1, "budget": "없음", "x": 1})

    state = journey.state
    assert state.project_spec.deployment_target is None
    assert [qa.field for qa in state.clarifications] == ["budget"]
    assert journey.prompt["questions"][0]["field"] == "deployment_target"


def test_decider_saying_sufficient_passes_clarify_despite_missing_signals():
    decider = MockDecider({"clarify.sufficient": DeciderResult(answer="yes", confidence=0.95)})

    assert Journey({"idea": IDEA}, JourneyDeps(decider=decider)).prompt["type"] == "decision"


@pytest.mark.parametrize(
    "override",
    [RuntimeError("down"), DeciderResult(answer="yes", confidence=0.2)],
)
def test_clarify_asks_when_decider_is_unusable(override):
    decider = MockDecider({"clarify.sufficient": override})

    assert Journey({"idea": IDEA}, JourneyDeps(decider=decider)).prompt["type"] == "clarify"


# Recommender
@pytest.mark.parametrize(
    "override",
    [
        DeciderResult(answer="question", confidence=0.69),
        DeciderResult(answer="not-an-option", confidence=0.99),
        RuntimeError("down"),
    ],
)
def test_unusable_recommendation_becomes_needs_comparison(override):
    decider = MockDecider({"recommend.agent.hitl": override})
    journey = Journey(deps=JourneyDeps(decider=decider))

    recommendation = journey.prompt["card"]["recommendation"]
    assert recommendation["status"] == "needs_comparison"
    assert recommendation["option_id"] is None

    journey.send({"action": "accept_recommendation"})
    assert "추천이 없습니다" in journey.prompt["error"]
    assert "agent.hitl" not in journey.state.decisions


def test_confidence_at_threshold_is_recommended():
    result = DeciderResult(answer="approval", confidence=0.7)
    decider = MockDecider({"recommend.agent.hitl": result})

    recommendation = Journey(deps=JourneyDeps(decider=decider)).prompt["card"]["recommendation"]

    assert recommendation["option_id"] == "approval"
    assert recommendation["reason"] == ""  # The card's reason explains its default, not this.


def test_blocked_option_is_never_recommended():
    journey = Journey()
    journey.select("approval")
    journey.select("gemini")
    journey.select("memory")
    journey.select("sync")
    journey.select("none")
    journey.select("external_api")

    card = journey.prompt["card"]
    assert card["card_id"] == "cloud.target"
    assert card["recommendation"]["option_id"] == "local"
    blocked = {v["option"]["id"] for v in card["options"] if v["blocked_reason"]}
    assert blocked == {"gcp", "aws"}


def test_recommendation_falls_back_when_the_default_is_blocked():
    journey = Journey()
    journey.select("none")
    journey.select("gemini")
    journey.select("postgres")
    journey.select("sync")
    journey.select("managed_k8s")
    journey.select("external_api")

    recommendation = journey.prompt["card"]["recommendation"]
    assert journey.card_id == "cloud.target"
    assert recommendation["status"] == "needs_comparison"


# Decision Gate
@pytest.mark.parametrize(
    "payload",
    [
        {"action": "select", "option_id": "missing"},
        {"action": "explode"},
        "아무거나",
        None,
    ],
)
def test_invalid_gate_input_reasks_the_same_card_without_recording(payload):
    journey = Journey().send(payload)

    assert journey.card_id == "agent.hitl"
    assert journey.prompt["error"]
    assert journey.state.decisions == {}


def test_gate_error_clears_after_a_valid_action():
    journey = Journey().send({"action": "explode"}).select("none")

    assert journey.prompt["error"] is None


def test_blocked_option_is_rejected_with_reason():
    journey = Journey().select("question")
    journey.select("gemini")
    journey.select("memory")
    journey.select("sync")
    journey.select("none")
    journey.select("external_api")

    journey.select("gcp")

    assert journey.card_id == "cloud.target"
    assert "체크포인터" in journey.prompt["error"]
    assert "cloud.target" not in journey.state.decisions


def test_option_preview_shows_what_comes_with_it():
    journey = Journey().select("none")

    views = {v["option"]["id"]: v for v in journey.prompt["card"]["options"]}
    assert views["ollama"]["implies"] == {"mlops.model_serving": "ollama"}
    assert views["gemini"]["implies"] == {}


def test_asking_returns_to_the_same_card_with_the_answer():
    journey = Journey().send({"action": "ask", "question": "interrupt가 뭐예요?"})

    assert journey.card_id == "agent.hitl"
    assert journey.prompt["qa"][0]["question"] == "interrupt가 뭐예요?"
    assert journey.prompt["qa"][0]["answered_by"] == "mock"
    assert journey.state.decisions == {}


def test_questions_per_card_are_limited_then_decision_still_works():
    journey = Journey()
    for _ in range(MAX_QUESTIONS_PER_CARD):
        journey.send({"action": "ask", "question": "질문"})
    journey.send({"action": "ask", "question": "한 번 더"})

    assert len(journey.prompt["qa"]) == MAX_QUESTIONS_PER_CARD
    assert "한도" in journey.prompt["error"]
    assert journey.select("none").card_id == "model.provider"


def test_deferred_card_returns_after_the_others():
    journey = Journey().send({"action": "defer"})
    assert journey.card_id == "model.provider"
    assert journey.prompt["progress"]["deferred"] == 1

    seen = []
    while journey.card_id != "agent.hitl":
        seen.append(journey.card_id)
        journey.send({"action": "accept_recommendation"})

    assert seen == list(REGISTRY.card_ids[1:])
    journey.select("none")
    assert journey.prompt is None
    assert journey.state.status == "completed"
    assert journey.state.deferred_cards == []


def test_deferring_every_remaining_card_rotates_instead_of_sticking():
    journey = Journey()
    for _ in REGISTRY.card_ids[:-2]:
        journey.send({"action": "accept_recommendation"})
    first = journey.card_id
    journey.send({"action": "defer"})
    second = journey.card_id
    journey.send({"action": "defer"})
    assert journey.card_id == first
    journey.send({"action": "defer"})
    assert journey.card_id == second


# Implies
def test_implied_card_is_skipped_and_recorded_separately():
    journey = Journey().select("none").select("ollama")
    seen = []
    for option_id in ("postgres", "sync", "none", "local"):
        seen.append(journey.card_id)
        journey.select(option_id)

    state = journey.state
    assert seen == [
        "data.checkpointer",
        "backend.execution",
        "devops.orchestration",
        "cloud.target",
    ]
    assert state.implied["mlops.model_serving"].by == "implied"
    assert state.implied["mlops.model_serving"].rationale
    assert "mlops.model_serving" not in state.decisions
    assert state.all_decisions["mlops.model_serving"].option_id == "ollama"
    assert state.status == "completed"


# Reopen
def test_reopening_a_decision_asks_it_again():
    journey = Journey().select("none")
    journey.send({"action": "reopen", "card_id": "agent.hitl"})

    assert journey.card_id == "agent.hitl"
    assert journey.state.decisions == {}


def test_reopening_the_source_reverts_implied_and_reopens_that_card():
    journey = Journey().select("none").select("ollama")
    assert "mlops.model_serving" in journey.state.implied

    journey.send({"action": "reopen", "card_id": "model.provider"})
    assert journey.card_id == "model.provider"
    assert journey.state.implied == {}
    assert "mlops.model_serving" in journey.state.pending_cards


def test_implied_or_undecided_cards_cannot_be_reopened():
    journey = Journey().select("none").select("ollama")

    journey.send({"action": "reopen", "card_id": "mlops.model_serving"})
    assert "앞선 선택" in journey.prompt["error"]
    assert "mlops.model_serving" in journey.state.implied

    journey.send({"action": "reopen", "card_id": "cloud.target"})
    assert "아직 결정" in journey.prompt["error"]


def test_reopen_keeps_decisions_that_are_not_affected():
    journey = Journey().select("question").select("gemini").select("postgres")
    journey.send({"action": "reopen", "card_id": "model.provider"})

    assert set(journey.state.decisions) == {"agent.hitl", "data.checkpointer"}
    assert journey.select("openai").card_id == "backend.execution"


# Consistency Reviewer
def journey_with_conflict():
    """Serving is chosen first, then the provider changes so a rule contradicts the choice."""
    journey = Journey().select("none").select("gemini").select("postgres").select("sync")
    journey.select("none").select("external_api")
    journey.send({"action": "reopen", "card_id": "model.provider"})
    journey.select("ollama").select("local")
    return journey


def test_review_stops_on_error_conflict_and_lists_issue():
    journey = journey_with_conflict()

    assert journey.prompt["type"] == "issues"
    assert journey.state.status == "needs_fix"
    issue = journey.prompt["issues"][0]
    assert issue["rule_id"] == "ollama-provider-means-ollama-serving"
    assert issue["card_ids"] == ["model.provider", "mlops.model_serving"]


@pytest.mark.parametrize(
    "payload",
    ["고쳐줘", {"action": "select", "option_id": "x"}, {"action": "reopen", "card_id": "nope"}],
)
def test_issue_gate_rejects_anything_but_reopening_a_decision(payload):
    journey = journey_with_conflict().send(payload)

    assert journey.prompt["type"] == "issues"
    assert journey.prompt["error"]


def test_reopening_the_implied_target_resolves_the_conflict():
    journey = journey_with_conflict()
    journey.send({"action": "reopen", "card_id": "mlops.model_serving"})

    state = journey.state
    assert journey.prompt is None
    assert state.status == "completed"
    assert state.implied["mlops.model_serving"].option_id == "ollama"
    assert state.conflicts == []


def test_reopening_the_source_returns_to_that_card_then_completes():
    journey = journey_with_conflict()
    journey.send({"action": "reopen", "card_id": "model.provider"})

    assert journey.card_id == "model.provider"
    journey.select("gemini")
    assert journey.prompt is None
    assert journey.state.status == "completed"


def test_warning_is_kept_without_stopping_the_journey():
    journey = Journey().select("none").select("gemini").select("postgres").select("sync")
    journey.select("none").select("ollama").select("gcp")

    state = journey.state
    assert journey.prompt is None
    assert state.status == "completed"
    assert [issue.rule_id for issue in state.review_issues] == ["self-serving-on-cloud"]


# Persistence and design guarantees
def test_journey_resumes_from_a_new_graph_instance_with_the_same_checkpointer():
    journey = Journey().select("question").select("gemini")

    restarted = build_graph(REGISTRY, checkpointer=journey.saver)
    result = restarted.invoke(
        resume_command({"action": "select", "option_id": "postgres"}), journey.config
    )

    assert result["__interrupt__"][0].value["card"]["card_id"] == "backend.execution"
    values = restarted.get_state(journey.config).values
    assert set(values["decisions"]) == {"agent.hitl", "model.provider", "data.checkpointer"}


def test_journeys_do_not_share_state():
    saver = InMemorySaver()
    first = Journey(checkpointer=saver).select("approval")
    second = Journey(checkpointer=saver)

    assert second.state.decisions == {}
    assert second.card_id == "agent.hitl"
    assert first.card_id == "model.provider"


def test_checkpoints_store_plain_json_not_python_objects():
    journey = Journey().select("none")

    stored = journey.saver.get(journey.config)["channel_values"]

    assert isinstance(stored["decisions"]["agent.hitl"], dict)
    assert isinstance(stored["current_card"], dict)
    assert isinstance(stored["trace"][0], dict)
    json.dumps({key: stored[key] for key in ("decisions", "current_card", "trace")})


def test_trace_records_deciders_without_user_text():
    journey = Journey().send({"action": "ask", "question": "민감한질문내용"})

    trace = journey.state.trace
    recommender = next(event for event in trace if event.node == "recommender")
    assert recommender.decider == "mock" and recommender.confidence == 0.9
    dump = " ".join(event.model_dump_json() for event in trace)
    assert "민감한" not in dump


def test_failures_do_not_log_user_text(caplog):
    decider = MockDecider({"recommend.agent.hitl": RuntimeError("민감한고객문의내용")})

    Journey(deps=JourneyDeps(decider=decider))

    assert "recommend.agent.hitl" in caplog.text
    assert "민감한" not in caplog.text


def test_node_writing_outside_its_fields_is_rejected():
    state = JourneyState(journey_id=uuid4(), project_spec=ProjectSpec(idea=IDEA))
    node = _guarded("advisor", lambda _: {"decisions": {}})

    with pytest.raises(OwnershipError, match="advisor"):
        node(state)
