"""ADR-018: the decider leaves out cards a project does not need, and code brings them back."""

import json
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from app.config import Settings
from app.journey.constraints import revived
from app.journey.deciders.base import DeciderQuestion, DeciderResult
from app.journey.deciders.jev import NONE_FITS, ROUTES, JevDecider
from app.journey.deciders.mock import MockDecider
from app.journey.design import DecisionRef
from app.journey.design_constraints import BLOCKING_CARDS, derive_design_constraints
from app.journey.graph import journey_config
from app.journey.nodes import SKIP_CONFIDENCE
from app.journey.package import build_package
from app.journey.service import JourneyService
from app.journey.services import JourneyDeps, build_deps
from app.journey.state import JourneyAction, JourneyState, ProjectSpec
from app.registry.loader import load_registry
from langgraph.checkpoint.memory import InMemorySaver
from pydantic import TypeAdapter

REGISTRY = load_registry()
ACTION = TypeAdapter(JourneyAction)
SPEC = ProjectSpec(
    idea="메모를 저장하고 나중에 찾아 주는 멀티 에이전트 서비스",
    goal="사용자가 저장한 메모를 다시 찾을 수 있는 상태",
    team_size=1,
    duration_weeks=4,
    budget="월 1만원",
    expected_users=1,
    weekly_hours=10,
    data_traits=["메모"],
    deployment_target="local_demo",
    has_gpu=False,
)
OLD_STATES = json.loads(
    (Path(__file__).parent / "fixtures" / "journey_state_before_design.json").read_text("utf-8")
)


def unneeded(confidence=0.9):
    return DeciderResult(answer="unneeded", confidence=confidence)


def skipping(*card_ids, confidence=0.9, **deps):
    overrides = {f"select.{card_id}": unneeded(confidence) for card_id in card_ids}
    return JourneyDeps(decider=MockDecider(overrides), **deps)


class Run:
    """Drives one journey through the service, the way the screen does."""

    def __init__(self, deps=None):
        self.service = JourneyService(REGISTRY, InMemorySaver(), deps)
        self.view = self.service.start(SPEC)

    @property
    def id(self):
        return self.view.journey_id

    @property
    def card_id(self):
        prompt = self.view.prompt
        return prompt["card"]["card_id"] if prompt and prompt["type"] == "decision" else None

    @property
    def state(self) -> JourneyState:
        values = self.service._graph.get_state(journey_config(self.id)).values
        return JourneyState.model_validate(values)

    def send(self, **action):
        self.view = self.service.act(self.id, self.view.revision, ACTION.validate_python(action))
        return self

    def answer_all(self, choices=None):
        """Answers every card asked, in order, and returns the cards that were asked."""
        asked = []
        while self.card_id and len(asked) < 30:
            card = self.view.prompt["card"]
            asked.append(card["card_id"])
            option_id = (choices or {}).get(card["card_id"]) or card["recommendation"]["option_id"]
            option_id = option_id or next(
                view["option"]["id"] for view in card["options"] if not view["blocked_reason"]
            )
            self.send(action="select", option_id=option_id)
        return asked

    def status(self, card_id):
        return next(card for card in self.view.cards if card.card_id == card_id)


class RecordingDecider(MockDecider):
    def __init__(self, overrides=None):
        super().__init__(overrides)
        self.asked: list[str] = []

    def decide_many(self, state, questions):
        self.asked += [question.id for question in questions]
        return super().decide_many(state, questions)


# Selection


def test_a_confidently_unneeded_card_is_not_asked_and_is_shown_as_skipped():
    run = Run(skipping("data.vector_store"))

    asked = run.answer_all()

    assert asked == [c for c in REGISTRY.card_ids if c != "data.vector_store"]
    status = run.status("data.vector_store")
    assert (status.state, status.skip_confidence, status.option_id) == ("skipped", 0.9, None)
    assert run.view.status == "completed"


def test_a_skipped_card_is_recorded_not_left_as_an_open_question():
    run = Run(skipping("data.vector_store"))
    run.answer_all()

    constraints = derive_design_constraints(run.state, REGISTRY)

    ref = next(ref for ref in constraints.decisions if ref.card_id == "data.vector_store")
    assert (ref.by, ref.option_id) == ("skipped", None)
    assert not any("검색 저장소" in unknown.text for unknown in constraints.unknowns)
    assert constraints.target.vector_store is None


def test_the_summary_and_package_say_a_skipped_card_does_not_apply():
    run = Run(skipping("data.vector_store"))
    run.answer_all()

    assert "## 해당 없음" in run.service.summary(run.id)
    files = build_package(run.service.design(run.id), REGISTRY, SPEC.idea)
    assert any("### 검색 저장소: 해당 없음" in text for text in files.values())


@pytest.mark.parametrize(
    "answer",
    [unneeded(SKIP_CONFIDENCE - 0.01), DeciderResult(answer="unknown", confidence=0.95)],
)
def test_an_unsure_or_unknown_answer_asks_the_card(answer):
    run = Run(JourneyDeps(decider=MockDecider({"select.data.vector_store": answer})))

    assert "data.vector_store" in run.answer_all()
    assert run.state.skipped_cards == {}


def test_cards_that_block_a_design_are_always_asked_and_never_judged():
    decider = RecordingDecider({f"select.{card_id}": unneeded() for card_id in BLOCKING_CARDS})
    run = Run(JourneyDeps(decider=decider))

    assert BLOCKING_CARDS <= set(run.answer_all())
    assert decider.asked == [
        f"select.{card_id}" for card_id in REGISTRY.card_ids if card_id not in BLOCKING_CARDS
    ]


def test_selection_runs_once_in_a_single_request():
    decider = RecordingDecider()
    run = Run(JourneyDeps(decider=decider))
    run.answer_all()
    run.send(action="reopen", card_id="agent.hitl")
    run.answer_all()

    assert len(decider.asked) == len(REGISTRY.cards) - len(BLOCKING_CARDS)
    assert [event.node for event in run.state.trace].count("card_selector") == 1


# Bringing a card back


def test_a_rule_on_decided_cards_brings_a_skipped_card_back():
    run = Run(skipping("data.checkpointer"))

    # A human check on a cloud deployment requires a checkpointer that survives a restart.
    asked = run.answer_all({"agent.hitl": "question", "cloud.target": "gcp"})

    assert asked[-2:] == ["cloud.target", "data.checkpointer"]
    assert run.state.decisions["data.checkpointer"].option_id != "memory"
    assert run.status("data.checkpointer").state == "decided"


def test_a_card_stays_skipped_while_no_rule_points_at_it():
    run = Run(skipping("data.checkpointer"))

    asked = run.answer_all({"agent.hitl": "none", "cloud.target": "gcp"})

    assert "data.checkpointer" not in asked
    assert run.status("data.checkpointer").state == "skipped"


def test_an_error_conflict_brings_its_undecided_card_back():
    chosen = {"devops.orchestration": "single_vm_k3s"}

    assert revived(REGISTRY, chosen, {"data.checkpointer"}) == {"data.checkpointer"}
    assert revived(REGISTRY, {"devops.orchestration": "none"}, {"data.checkpointer"}) == set()


def test_warnings_and_rules_on_the_skipped_card_alone_do_not_bring_it_back():
    # api-provider-with-self-serving is a warning: an API user really may not need serving.
    assert revived(REGISTRY, {"model.provider": "gemini"}, {"mlops.model_serving"}) == set()
    # pgvector-needs-postgres only matters if the skipped vector store were pgvector.
    assert revived(REGISTRY, {"data.primary_db": "sqlite"}, {"data.vector_store"}) == set()


def test_a_card_goes_back_out_when_the_decision_pointing_at_it_changes():
    run = Run(skipping("data.checkpointer"))
    choices = {"agent.hitl": "question", "cloud.target": "gcp"}
    asked = run.answer_all(choices)
    assert "data.checkpointer" in asked

    # Reopening the checkpointer, then removing the human check, leaves nothing requiring it.
    run.send(action="reopen", card_id="data.checkpointer")
    run.send(action="reopen", card_id="agent.hitl")
    run.answer_all({"agent.hitl": "none"})

    assert run.status("data.checkpointer").state == "skipped"


# Putting a skipped card back


def test_a_skipped_card_can_be_put_back_during_the_journey():
    run = Run(skipping("data.vector_store"))
    assert run.card_id == "agent.topology"

    run.send(action="reopen", card_id="data.vector_store")

    assert run.state.skipped_cards == {}
    assert "data.vector_store" in run.answer_all()
    assert run.status("data.vector_store").state == "decided"


def test_a_skipped_card_can_be_put_back_after_finishing():
    run = Run(skipping("data.vector_store"))
    run.answer_all()
    assert run.view.can_reopen

    run.send(action="reopen", card_id="data.vector_store")

    assert run.answer_all({"data.vector_store": "none"}) == ["data.vector_store"]
    assert run.view.status == "completed"
    assert run.state.decisions["data.vector_store"].option_id == "none"


# Turning it off and failures


def test_selection_can_be_turned_off():
    run = Run(skipping("data.vector_store", card_selection=False))

    assert run.answer_all() == list(REGISTRY.card_ids)


def test_the_setting_reaches_the_journey(monkeypatch):
    assert build_deps(Settings(_env_file=None), REGISTRY).card_selection is True
    monkeypatch.setenv("APP_CARD_SELECTION", "false")
    assert build_deps(Settings(_env_file=None), REGISTRY).card_selection is False


def test_a_failed_selection_asks_every_card():
    decider = MockDecider({"batch": RuntimeError("down"), "select.data.vector_store": unneeded()})
    run = Run(JourneyDeps(decider=decider))

    assert run.answer_all() == list(REGISTRY.card_ids)
    event = next(event for event in run.state.trace if event.node == "card_selector")
    assert (event.decider, event.model_id) == ("mock", None)


def jev(handler):
    route = ROUTES["opencode"]
    client = httpx.Client(base_url=route.base_url, transport=httpx.MockTransport(handler))
    return JevDecider("opencode", REGISTRY, client=client)


def jev_answers(**choices):
    """Native route shape (see test_models), with one answer per question key."""
    return {
        "model": "jev-1.13-free",
        "answers": {
            key: {"type": "choice", "choice": choice, "confidence": confidence}
            for key, (choice, confidence) in choices.items()
        },
        "usage": {"input_tokens": 500, "output_tokens": 40},
    }


def question(question_id):
    return DeciderQuestion(id=question_id, text="필요한가요?", choices=("needed", "unneeded"))


def test_jev_sends_several_questions_in_one_request_and_keeps_their_ids():
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json=jev_answers(q0=("needed", 0.9), q1=("unneeded", 0.88)))

    state = JourneyState(journey_id=uuid4(), project_spec=SPEC)
    batch = jev(handler).decide_many(state, [question("select.a"), question("select.b")])

    assert len(seen) == 1
    assert list(seen[0]["questions"]) == ["q0", "q1"]
    assert all(NONE_FITS in q["criteria"] for q in seen[0]["questions"].values())
    answers = {k: (v.answer, v.confidence) for k, v in batch.results.items()}
    assert answers == {"select.a": ("needed", 0.9), "select.b": ("unneeded", 0.88)}
    assert (batch.model_id, batch.input_tokens, batch.output_tokens) == ("jev-1.13-free", 500, 40)


def test_jev_selection_skips_only_confident_unneeded_cards():
    candidates = [c for c in REGISTRY.card_ids if c not in BLOCKING_CARDS]
    answers = {f"q{i}": ("needed", 0.9) for i in range(len(candidates))}
    answers |= {"q0": ("unneeded", 0.95), "q1": ("unneeded", 0.8)}

    def handler(request):
        return httpx.Response(200, json=jev_answers(**answers))

    run = Run(JourneyDeps(decider=jev(handler)))

    assert set(run.state.skipped_cards) == {candidates[0]}
    assert run.state.skipped_cards[candidates[0]].decider == "jev"
    event = next(event for event in run.state.trace if event.node == "card_selector")
    assert (event.decider, event.input_tokens, event.output_tokens) == ("jev", 500, 40)


def test_a_jev_answer_missing_a_question_skips_nothing():
    def handler(request):
        return httpx.Response(200, json=jev_answers(q0=("unneeded", 0.95)))

    run = Run(JourneyDeps(decider=jev(handler)))

    assert run.state.skipped_cards == {}


# Journeys saved before selection existed


def test_a_journey_saved_before_selection_has_nothing_skipped():
    for saved in OLD_STATES.values():
        state = JourneyState.model_validate(saved)
        assert state.skipped_cards == {} and state.skipped == set()


def test_only_a_deferred_or_skipped_reference_has_no_option():
    assert DecisionRef(card_id="data.vector_store", card_version=1, by="skipped").option_id is None
    with pytest.raises(ValueError):
        DecisionRef(card_id="data.vector_store", card_version=1, by="skipped", option_id="none")
