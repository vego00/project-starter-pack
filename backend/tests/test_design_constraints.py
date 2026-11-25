import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from app.journey.constraints import Conflict
from app.journey.design_constraints import (
    BLOCKING_CARDS,
    CONSTRAINING_CARDS,
    HUMAN_CHECKS,
    OUT_OF_SCOPE_CARDS,
    RESUMABLE,
    TOPOLOGY,
    derive_design_constraints,
)
from app.journey.state import Decision, JourneyState, ProjectSpec
from app.registry.loader import load_registry

REGISTRY = load_registry()
NOW = datetime(2026, 11, 5, tzinfo=UTC)
IDEA = "강의 자료를 찾아 답하는 멀티 에이전트 서비스"
AGENT_PATH = {
    "agent.topology": "pipeline",
    "agent.hitl": "none",
    "model.provider": "gemini",
    "data.primary_db": "postgres",
    "data.vector_store": "pgvector",
    "data.checkpointer": "postgres",
    "backend.execution": "sync",
    "backend.implementation": "code",
    "devops.orchestration": "none",
    "mlops.model_serving": "external_api",
    "cloud.target": "gcp",
}
OLD_STATES = json.loads(
    (Path(__file__).parent / "fixtures" / "journey_state_before_design.json").read_text("utf-8")
)


def decision(card_id, option_id, by="user", version=None):
    card_version = version or REGISTRY.card(card_id).version
    return Decision(card_id=card_id, card_version=card_version, option_id=option_id, by=by, at=NOW)


def state(choices=None, *, implied=None, spec=None, review_issues=None):
    return JourneyState(
        journey_id=uuid4(),
        project_spec=ProjectSpec(idea=IDEA, **(spec or {})),
        decisions={
            k: decision(k, v) for k, v in (AGENT_PATH if choices is None else choices).items()
        },
        implied=implied or {},
        review_issues=review_issues or [],
    )


def with_choice(**overrides):
    return {**AGENT_PATH, **{k.replace("__", "."): v for k, v in overrides.items()}}


def derive(choices=None, **kwargs):
    return derive_design_constraints(state(choices, **kwargs), REGISTRY)


# Every option has a meaning


@pytest.mark.parametrize(
    ("card_id", "table"),
    [("agent.topology", TOPOLOGY), ("agent.hitl", HUMAN_CHECKS), ("data.checkpointer", RESUMABLE)],
)
def test_every_option_of_a_constraining_card_has_a_meaning(card_id, table):
    assert {option.id for option in REGISTRY.card(card_id).options} == set(table)


def test_every_card_is_either_used_or_skipped_with_a_reason():
    assert CONSTRAINING_CARDS | set(OUT_OF_SCOPE_CARDS) == set(REGISTRY.card_ids)
    assert not CONSTRAINING_CARDS & set(OUT_OF_SCOPE_CARDS)
    assert BLOCKING_CARDS <= CONSTRAINING_CARDS
    assert {card.card_id for card in derive().out_of_scope} == set(OUT_OF_SCOPE_CARDS)
    assert all(card.reason for card in derive().out_of_scope)


# Topology limits the kind of structure, not an exact design


@pytest.mark.parametrize(
    ("option", "minimum", "maximum", "routing"),
    [
        ("pipeline", 2, None, "fixed"),
        ("supervisor", 2, None, "model"),
        ("hierarchical", 2, None, "model_with_subgraphs"),
    ],
)
def test_topology_bounds_the_agent_nodes(option, minimum, maximum, routing):
    target = derive(with_choice(agent__topology=option)).target

    assert (target.min_agent_nodes, target.max_agent_nodes, target.routing) == (
        minimum,
        maximum,
        routing,
    )


@pytest.mark.parametrize(
    ("option", "checks"),
    [("none", []), ("question", ["question"]), ("approval", ["approval"])],
)
def test_hitl_sets_the_human_checks(option, checks):
    assert derive(with_choice(agent__hitl=option)).target.human_checks == checks


@pytest.mark.parametrize(("option", "resumable"), [("memory", False), ("postgres", True)])
def test_checkpointer_sets_whether_a_run_resumes(option, resumable):
    assert derive(with_choice(data__checkpointer=option)).target.resumable is resumable


def test_a_custom_store_must_be_checked_by_the_user():
    result = derive(with_choice(data__checkpointer="other"))

    assert result.target.resumable is None
    assert any("재개" in warning for warning in result.warnings)


def test_provider_scope_never_goes_beyond_the_choice():
    assert derive().target.allowed_providers == ["gemini"]


def test_execution_is_passed_through():
    assert derive(with_choice(backend__execution="queue")).target.execution == "queue"


def test_storage_choices_are_passed_through():
    target = derive(with_choice(data__primary_db="none", data__vector_store="none")).target

    assert (target.primary_db, target.vector_store) == ("none", "none")
    assert derive().target.vector_store == "pgvector"


# Target service and starter stay apart


@pytest.mark.parametrize(
    "choice",
    [
        {"agent__hitl": "none"},
        {"data__checkpointer": "memory"},
    ],
)
def test_the_starter_review_does_not_depend_on_the_target_choices(choice):
    starter = derive(with_choice(**choice)).starter

    assert starter.user_review_required is True
    assert starter.review_survives_restart is True


def test_no_human_check_in_the_target_is_not_a_warning_about_the_review():
    assert derive(with_choice(agent__hitl="none")).unknowns == []


# The first version designs multi-agent services only


def test_only_the_single_agent_structure_allows_one_agent():
    # ADR-017 changed on 2026-11-06: a single agent is allowed, multi-agent stays the default.
    assert {o.id for o in REGISTRY.card("agent.topology").options} == set(TOPOLOGY)
    assert TOPOLOGY["single"][:2] == (1, 1)
    assert all(minimum >= 2 for key, (minimum, _, _) in TOPOLOGY.items() if key != "single")
    assert REGISTRY.card("agent.topology").default_recommendation.option == "pipeline"


# Deferred decisions and card versions


@pytest.mark.parametrize("card_id", sorted(CONSTRAINING_CARDS))
def test_a_deferred_card_surfaces_as_unknown(card_id):
    choices = {k: v for k, v in AGENT_PATH.items() if k != card_id}

    result = derive(choices)

    assert len(result.unknowns) == 1
    assert REGISTRY.card(card_id).title in result.unknowns[0].text
    assert result.unknowns[0].blocks_confirmation is (card_id in BLOCKING_CARDS)
    ref = next(ref for ref in result.decisions if ref.card_id == card_id)
    assert (ref.by, ref.option_id) == ("deferred", None)


def test_a_deferred_card_leaves_its_limit_empty():
    choices = {k: v for k, v in AGENT_PATH.items() if k != "agent.topology"}

    target = derive(choices).target

    assert (target.min_agent_nodes, target.max_agent_nodes, target.routing) == (None, None, None)


@pytest.mark.parametrize("card_id", sorted(OUT_OF_SCOPE_CARDS))
def test_a_deferred_deployment_card_is_not_an_unknown(card_id):
    choices = {k: v for k, v in AGENT_PATH.items() if k != card_id}

    assert derive(choices).unknowns == []


def test_snapshot_keeps_the_version_the_user_decided_on():
    journey = state()
    journey.decisions["agent.topology"] = decision("agent.topology", "supervisor", version=1)

    result = derive_design_constraints(journey, REGISTRY)

    ref = next(ref for ref in result.decisions if ref.card_id == "agent.topology")
    assert ref.card_version == 1
    assert result.target.routing == "model"
    assert any(REGISTRY.card("agent.topology").title in warning for warning in result.warnings)
    assert result.unknowns == []


def test_an_option_that_no_longer_exists_must_be_chosen_again():
    journey = state()
    journey.decisions["agent.topology"] = decision("agent.topology", "swarm", version=1)

    result = derive_design_constraints(journey, REGISTRY)

    assert result.target.routing is None
    assert [u.blocks_confirmation for u in result.unknowns] == [True]
    assert "다시 골라야" in result.unknowns[0].text


def test_a_decision_on_a_removed_card_is_reported():
    journey = state()
    journey.decisions["agent.memory"] = Decision(
        card_id="agent.memory", card_version=1, option_id="x", by="user", at=NOW
    )

    assert any("agent.memory" in w for w in derive_design_constraints(journey, REGISTRY).warnings)


def test_a_completed_journey_saved_on_old_cards_still_derives():
    old = JourneyState.model_validate(OLD_STATES["completed"])
    assert old.decisions["agent.topology"].card_version == 1

    result = derive_design_constraints(old, REGISTRY)

    assert result.target.routing == "fixed"
    assert result.target.allowed_providers == ["gemini"]
    # Cards added after the journey finished were never asked: open, but not blocking.
    assert [(u.text, u.blocks_confirmation) for u in result.unknowns] == [
        ("아직 정하지 않은 결정: 데이터 저장소", False),
        ("아직 정하지 않은 결정: 검색 저장소", False),
        ("아직 정하지 않은 결정: 구현 방식", False),
    ]
    changed = {"Agent 구조"}
    assert {w.split(" 카드가")[0] for w in result.warnings if "바뀌었어요" in w} == changed


# Answers that contradict a choice


def test_a_public_service_on_local_only_blocks_confirmation():
    choices = with_choice(cloud__target="local")

    result = derive(choices, spec={"deployment_target": "public_service"})

    assert [u.blocks_confirmation for u in result.unknowns] == [True]


def test_a_small_group_on_local_only_warns():
    result = derive(with_choice(cloud__target="local"), spec={"deployment_target": "small_group"})

    assert result.unknowns == []
    assert any("로컬" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("choice", "spec", "phrase"),
    [
        ({"model__provider": "ollama"}, {"has_gpu": False}, "GPU"),
        ({"mlops__model_serving": "vllm"}, {"has_gpu": False}, "GPU"),
        ({"data__checkpointer": "memory"}, {"deployment_target": "public_service"}, "메모리"),
        ({}, {"data_traits": ["개인정보 포함"]}, "개인정보"),
    ],
)
def test_contradicting_answers_warn(choice, spec, phrase):
    assert any(phrase in w for w in derive(with_choice(**choice), spec=spec).warnings)


@pytest.mark.parametrize(
    ("choice", "spec"),
    [
        ({"model__provider": "ollama"}, {"has_gpu": True}),
        ({"model__provider": "ollama"}, {}),
        ({"data__checkpointer": "memory"}, {"deployment_target": "local_demo"}),
        ({"model__provider": "ollama"}, {"data_traits": ["개인정보 포함"], "has_gpu": True}),
        ({"cloud__target": "local"}, {"deployment_target": "local_demo"}),
    ],
)
def test_matching_or_unanswered_conditions_stay_silent(choice, spec):
    result = derive(with_choice(**choice), spec=spec)

    assert result.unknowns == []
    assert result.warnings == []


def test_review_warnings_are_carried_over_and_errors_are_not():
    issues = [
        Conflict(rule_id="w", severity="warning", message="확인할 점", card_ids=["a"]),
        Conflict(rule_id="e", severity="error", message="해결할 점", card_ids=["a"]),
    ]

    assert derive(review_issues=issues).warnings == ["확인할 점"]


def test_the_same_journey_always_derives_the_same_limits():
    journey = state()

    first = derive_design_constraints(journey, REGISTRY)

    assert derive_design_constraints(journey, REGISTRY) == first
