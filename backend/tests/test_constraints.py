import pytest
from app.journey.constraints import evaluate, preview
from app.journey.controller import next_card
from app.registry.loader import Registry, load_registry
from app.registry.schema import DecisionCard


@pytest.fixture(scope="module")
def registry():
    return load_registry()


def rule_ids(conflicts):
    return {conflict.rule_id for conflict in conflicts}


def test_nothing_decided_means_all_pending_and_nothing_blocked(registry):
    result = evaluate(registry, {})

    assert result.pending == list(registry.card_ids)
    assert result.conflicts == [] and result.implied == {} and result.blocked == {}


# requires
def test_requires_blocks_violating_option_while_target_is_undecided(registry):
    result = evaluate(registry, {"agent.hitl": "question", "cloud.target": "gcp"})

    assert set(result.blocked["data.checkpointer"]) == {"memory"}
    assert result.conflicts == []


def test_requires_stays_silent_until_all_conditions_hold(registry):
    assert "data.checkpointer" not in evaluate(registry, {"agent.hitl": "question"}).blocked
    local = {"agent.hitl": "question", "cloud.target": "local"}
    assert "data.checkpointer" not in evaluate(registry, local).blocked


def test_requires_blocks_the_last_undecided_condition_in_any_position(registry):
    # Target is decided first: the option that would complete the violation is unavailable.
    result = evaluate(registry, {"agent.hitl": "approval", "data.checkpointer": "memory"})

    assert set(result.blocked["cloud.target"]) == {"gcp", "aws"}


def test_requires_violation_is_a_conflict_once_all_are_decided(registry):
    result = evaluate(
        registry,
        {"agent.hitl": "approval", "data.checkpointer": "memory", "cloud.target": "aws"},
    )

    assert rule_ids(result.conflicts) == {"hitl-needs-durable-checkpointer"}
    assert result.conflicts[0].severity == "error"


def test_pgvector_needs_postgres_as_the_primary_db(registry):
    assert set(
        evaluate(registry, {"data.vector_store": "pgvector"}).blocked["data.primary_db"]
    ) == {
        "sqlite",
        "none",
    }
    both = evaluate(registry, {"data.vector_store": "pgvector", "data.primary_db": "sqlite"})
    assert rule_ids(both.conflicts) == {"pgvector-needs-postgres"}
    other = evaluate(registry, {"data.vector_store": "qdrant", "data.primary_db": "none"})
    assert other.conflicts == []


def test_requires_is_satisfied_by_an_allowed_option(registry):
    result = evaluate(
        registry,
        {"agent.hitl": "approval", "data.checkpointer": "postgres", "cloud.target": "aws"},
    )

    assert result.conflicts == []


def test_managed_k8s_requires_cloud(registry):
    result = evaluate(registry, {"devops.orchestration": "managed_k8s"})

    assert set(result.blocked["cloud.target"]) == {"local"}


# conflicts
def test_error_conflict_blocks_and_reports(registry):
    blocked = evaluate(registry, {"devops.orchestration": "local_k8s"}).blocked
    assert set(blocked["data.checkpointer"]) == {"memory"}

    result = evaluate(
        registry, {"devops.orchestration": "local_k8s", "data.checkpointer": "memory"}
    )
    assert rule_ids(result.conflicts) == {"orchestration-with-memory-state"}


def test_warning_conflict_reports_without_blocking(registry):
    partial = evaluate(registry, {"mlops.model_serving": "ollama"})
    assert "cloud.target" not in partial.blocked

    result = evaluate(registry, {"mlops.model_serving": "ollama", "cloud.target": "gcp"})
    assert [c.severity for c in result.conflicts] == ["warning"]


def test_api_provider_with_self_serving_is_a_warning(registry):
    result = evaluate(registry, {"model.provider": "gemini", "mlops.model_serving": "ollama"})
    assert rule_ids(result.conflicts) == {"api-provider-with-self-serving"}
    assert [c.severity for c in result.conflicts] == ["warning"]
    assert "mlops.model_serving" not in result.blocked


def test_api_provider_with_external_serving_is_fine(registry):
    result = evaluate(registry, {"model.provider": "gemini", "mlops.model_serving": "external_api"})
    assert result.conflicts == []


# implies
def test_implies_decides_the_card_and_removes_it_from_pending(registry):
    result = evaluate(registry, {"model.provider": "ollama"})

    assert result.implied["mlops.model_serving"].option_id == "ollama"
    assert "mlops.model_serving" not in result.pending


def test_implies_does_not_fire_for_other_options(registry):
    assert evaluate(registry, {"model.provider": "gemini"}).implied == {}


def test_implies_never_overwrites_a_user_decision(registry):
    result = evaluate(registry, {"model.provider": "ollama", "mlops.model_serving": "external_api"})

    assert result.implied == {}
    assert rule_ids(result.conflicts) == {"ollama-provider-means-ollama-serving"}
    assert result.conflicts[0].severity == "error"


def test_implied_choice_feeds_other_rules(registry):
    result = evaluate(registry, {"model.provider": "ollama", "cloud.target": "gcp"})

    assert rule_ids(result.conflicts) == {"self-serving-on-cloud"}


def test_reverting_the_source_reverts_the_implied_choice(registry):
    assert "mlops.model_serving" in evaluate(registry, {"model.provider": "gemini"}).pending


def option(option_id):
    return {
        "id": option_id,
        "name": "n",
        "summary": "s",
        "learning_difficulty": "low",
        "ops_burden": "low",
        "cost_nature": "c",
    }


def make_card(card_id, **rules):
    return DecisionCard.model_validate(
        {
            "card_id": card_id,
            "version": 1,
            "layer": card_id.split(".")[0],
            "title": "t",
            "question": "q",
            "options": [option("a"), option("b")],
            "default_recommendation": {"option": "a", "reason": "r"},
            **rules,
        }
    )


def implies(rule_id, source, target, value="a"):
    return {
        "id": rule_id,
        "when": [{"card": source, "in": ["a"]}],
        "then": {"card": target, "option": value},
        "message": "m",
    }


def test_implies_chain_resolves_regardless_of_rule_order():
    registry = Registry(
        [
            make_card("agent.x", implies=[implies("y-to-z", "model.y", "data.z")]),
            make_card("model.y", implies=[implies("w-to-y", "agent.w", "model.y")]),
            make_card("agent.w"),
            make_card("data.z"),
        ]
    )

    result = evaluate(registry, {"agent.w": "a"})

    assert set(result.implied) == {"model.y", "data.z"}


def test_implies_cycle_terminates():
    registry = Registry(
        [
            make_card("agent.x", implies=[implies("x-to-y", "agent.x", "model.y")]),
            make_card("model.y", implies=[implies("y-to-x", "model.y", "agent.x")]),
        ]
    )

    result = evaluate(registry, {"agent.x": "a"})

    assert set(result.implied) == {"model.y"} and result.conflicts == []


def test_contradicting_implies_report_a_conflict():
    registry = Registry(
        [
            make_card(
                "agent.x",
                implies=[
                    implies("to-a", "agent.x", "model.y", "a"),
                    implies("to-b", "agent.x", "model.y", "b"),
                ],
            ),
            make_card("model.y"),
        ]
    )

    result = evaluate(registry, {"agent.x": "a"})

    assert result.implied["model.y"].option_id == "a"
    assert rule_ids(result.conflicts) == {"to-b"}


# preview
def test_preview_lists_what_an_option_would_change(registry):
    impact = preview(registry, {}, "model.provider", "ollama")

    assert impact.implied["mlops.model_serving"].option_id == "ollama"
    assert preview(registry, {}, "model.provider", "gemini").implied == {}


def test_preview_lists_only_new_conflicts(registry):
    chosen = {"mlops.model_serving": "ollama"}

    assert rule_ids(preview(registry, chosen, "cloud.target", "gcp").conflicts) == {
        "self-serving-on-cloud"
    }
    assert preview(registry, chosen, "cloud.target", "local").conflicts == []


# controller
def test_controller_keeps_registry_order_and_serves_deferred_last():
    assert next_card(["a", "b", "c"], []) == "a"
    assert next_card(["a", "b", "c"], ["a"]) == "b"
    assert next_card(["a", "b"], ["b", "a"]) == "b"
    assert next_card(["b"], ["a", "b"]) == "b"
    assert next_card([], ["a"]) is None
