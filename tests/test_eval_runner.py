"""The evaluation runner works end to end with mock deps, so CI can check it without a model."""

import importlib.util
import json
from pathlib import Path

import pytest
from app.journey.services import JourneyDeps
from app.registry.loader import load_registry

RUNNER = Path(__file__).resolve().parents[1] / "benchmarks" / "run.py"
spec = importlib.util.spec_from_file_location("eval_runner", RUNNER)
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
REGISTRY = load_registry()


def test_every_case_names_real_cards_and_options():
    cases = runner.load_cases()

    assert {case["id"] for case in cases} >= {"C1", "C3", "C4"}
    for case in cases:
        assert case["status"] in {"초안", "확정"} and case["notion"].startswith("https://")
        for card_id, option_id in case["selection"].items():
            assert REGISTRY.card(card_id).option(option_id) is not None, (case["id"], card_id)
        assert set(case["must_ask"] + case["may_skip"]) <= set(REGISTRY.card_ids)


@pytest.mark.parametrize("mode", ["flow", "blank"])
def test_a_case_runs_with_mock_deps(mode):
    case = next(c for c in runner.load_cases(["C4"]))

    result = runner.run_case(case, mode, JourneyDeps(), REGISTRY)

    assert (result["case"], result["mode"]) == ("C4", mode)
    assert result["design"]["source"] == "template"  # No designer: the labelled template.
    assert result["failed_rules"] == [] and result["http_status"] == []
    if mode == "flow":
        assert result["status"] == "completed"
        assert result["must_ask_missed"] == []
        # The mock skips nothing, and earlier stages are asked first.
        by_stage = sorted(REGISTRY.cards, key=lambda card: card.stage)
        assert result["asked"] == [card.card_id for card in by_stage]


def test_the_case_choice_is_used_and_a_blocked_one_is_never_sent():
    case = {"selection": {"data.checkpointer": "memory"}}
    card = {
        "card_id": "data.checkpointer",
        "recommendation": {"option_id": "postgres"},
        "options": [
            {"option": {"id": "memory"}, "blocked_reason": "재시작 후 남지 않아요"},
            {"option": {"id": "postgres"}, "blocked_reason": None},
        ],
    }

    assert runner._choose(case, card, REGISTRY) == "postgres"
    assert runner._choose({"selection": {}}, card, REGISTRY) == "postgres"


def test_log_lines_become_rules_fields_and_statuses():
    found = runner.log_findings(
        [
            "Design draft broke the contract fields=['state_fields.0.writers:too_short']",
            "Design call failed type=ClientError status=429",
            "Design failed validation errors=2 rules=['loop.no_limit', 'decision.too_few_agents']",
        ]
    )

    assert found == {
        "failed_rules": [["loop.no_limit", "decision.too_few_agents"]],
        "contract_fields": [["state_fields.0.writers:too_short"]],
        "http_status": ["429"],
    }


def test_main_writes_a_summary_and_raw_results(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "REPORTS_DIR", tmp_path)
    monkeypatch.setenv("APP_PROVIDER", "mock")
    monkeypatch.setenv("APP_DECIDER", "mock")

    out = runner.main(["--cases", "C1", "--modes", "flow,blank", "--runs", "1", "--label", "t"])

    summary = (out / "summary.md").read_text("utf-8")
    assert "| C1 (확정) | flow | 1 | 0/1 |" in summary
    raw = json.loads((out / "results.json").read_text("utf-8"))
    assert [r["mode"] for r in raw["results"]] == ["flow", "blank"]
