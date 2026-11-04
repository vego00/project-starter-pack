import pytest
from app.registry.loader import Registry, RegistryError, load_registry
from app.registry.schema import LAYERS, DecisionCard
from pydantic import ValidationError


def card(card_id="agent.x", **overrides) -> dict:
    option = {
        "name": "이름",
        "summary": "설명",
        "learning_difficulty": "low",
        "ops_burden": "low",
        "cost_nature": "없음",
    }
    return {
        "card_id": card_id,
        "version": 1,
        "layer": card_id.split(".")[0],
        "question": "질문",
        "options": [{"id": "a", **option}, {"id": "b", **option}],
        "default_recommendation": {"option": "a", "reason": "이유"},
        **overrides,
    }


def test_shipped_cards_cover_each_layer_once_in_journey_order():
    registry = load_registry()

    assert [c.layer for c in registry.cards] == list(LAYERS)


def test_shipped_cards_do_not_claim_unchecked_sources():
    # checked_at means a person verified the sources; drafts must not pretend otherwise.
    for shipped in load_registry().cards:
        assert bool(shipped.sources) == (shipped.checked_at is not None)


@pytest.mark.parametrize(
    "overrides",
    [
        {"default_recommendation": {"option": "missing", "reason": "이유"}},
        {"signals": {"missing": ["신호"]}},
        {"artifacts": {"missing": ["compose:x"]}},
        {"layer": "model"},
        {"unknown_field": 1},
    ],
)
def test_card_rejects_inconsistent_definitions(overrides):
    with pytest.raises(ValidationError):
        DecisionCard.model_validate(card(**overrides))


def test_card_rejects_duplicate_option_ids():
    raw = card()
    raw["options"][1]["id"] = "a"

    with pytest.raises(ValidationError):
        DecisionCard.model_validate(raw)


@pytest.mark.parametrize(
    "condition",
    [{"card": "agent.x"}, {"card": "agent.x", "in": ["a"], "not_in": ["b"]}],
)
def test_condition_needs_exactly_one_operator(condition):
    rule = {"id": "r", "when": [condition], "require": {"card": "agent.x", "in": ["a"]}}

    with pytest.raises(ValidationError):
        DecisionCard.model_validate(card(requires=[{**rule, "message": "m"}]))


@pytest.mark.parametrize(
    "then",
    [{"card": "agent.missing", "option": "a"}, {"card": "agent.x", "option": "missing"}],
)
def test_registry_rejects_rules_pointing_at_nothing(then):
    rule = {"id": "r", "when": [{"card": "agent.x", "in": ["a"]}], "then": then, "message": "m"}

    with pytest.raises(RegistryError, match="unknown"):
        Registry([DecisionCard.model_validate(card(implies=[rule]))])


def test_registry_rejects_duplicate_cards_and_rule_ids():
    plain = DecisionCard.model_validate(card())
    with pytest.raises(RegistryError, match="duplicate card_id"):
        Registry([plain, plain])

    rule = {"id": "r", "when": [{"card": "agent.x", "in": ["a"]}], "message": "m"}
    rule["then"] = {"card": "agent.x", "option": "b"}
    first = DecisionCard.model_validate(card(implies=[rule]))
    second = DecisionCard.model_validate(card("model.y", implies=[rule]))
    with pytest.raises(RegistryError, match="duplicate rule id"):
        Registry([first, second])


def test_load_requires_every_layer(tmp_path):
    with pytest.raises(RegistryError, match="layers without a card"):
        load_registry(tmp_path)
    assert load_registry(tmp_path, require_all_layers=False).cards == ()


def test_new_card_needs_only_a_yaml_file(tmp_path):
    (tmp_path / "x.yaml").write_text(
        "card_id: agent.topology\nversion: 1\nlayer: agent\nquestion: 질문\n"
        "default_recommendation: {option: a, reason: 이유}\noptions:\n"
        + "".join(
            f"  - {{id: {i}, name: n, summary: s, learning_difficulty: low, "
            "ops_burden: low, cost_nature: c}\n"
            for i in "ab"
        ),
        encoding="utf-8",
    )

    registry = load_registry(tmp_path, require_all_layers=False)

    assert registry.card_ids == ("agent.topology",)
