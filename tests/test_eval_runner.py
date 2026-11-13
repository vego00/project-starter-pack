"""The evaluation runner works end to end with mock deps, so CI can check it without a model."""

import importlib.util
import json
from pathlib import Path

import pytest
from app.journey.services import JourneyDeps, StartFailure, StartReply
from app.journey.start import StartChange
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


class ScriptedWriter:
    """Test doubles are independent of case expectations; never used as a quality baseline."""

    def __init__(self, *replies):
        self.replies = iter(replies)
        self.seen = []

    def write(self, current, chat, message, focus):
        self.seen.append(message)
        return next(self.replies)


def extracted(case, *, budget=False):
    # A hand-written provider fixture. Tests deliberately mutate it to check the evaluator.
    idea = case["idea"]
    changes = [
        StartChange(
            field="goal", value="강사가 피드백 초안을 검토하고 전달한다", evidence="피드백 초안"
        ),
        StartChange(
            field="context", value="매주 수강생 30명이 과제를 제출한다", evidence="수강생 30명"
        ),
        StartChange(field="boundary", value="강사 검토 후 전달", evidence="읽고 고친 다음에만"),
    ]
    for field, value, quote in [
        ("team_size", "2", "2명"),
        ("duration_weeks", "6", "6주"),
        ("weekly_hours", "15", "15시간"),
        ("expected_users", "31", "31명"),
        ("deployment_target", "small_group", "small_group"),
        ("has_gpu", "no", "GPU는 없습니다"),
    ]:
        if quote in idea:
            changes.append(StartChange(field=field, value=value, evidence=quote))
    if budget:
        changes.append(StartChange(field="budget", value="월 10만원", evidence="월 10만원"))
    return StartReply(changes=changes, model_id="scripted-test")


def intake(name):
    return runner.load_cases([name])[0]


def test_intake_only_sends_idea_and_uses_fresh_sessions():
    case = intake("C4-intake-base")
    writer = ScriptedWriter(extracted(case), extracted(case))
    deps = JourneyDeps(start_writer=writer)
    first = runner.run_case(case, "intake", deps, REGISTRY)
    second = runner.run_case(case, "intake", deps, REGISTRY)
    assert first["journey_id"] != second["journey_id"]
    assert writer.seen == [case["idea"], case["idea"]]
    assert all(c["status"] == "pass" for c in first["checks"])
    assert first["start_calls"] == 1 and first["design_calls"] == 0


def test_missing_budget_and_card_default_are_different_checkpoints():
    case = intake("C4-intake-default")
    result = runner.run_case(
        case, "intake", JourneyDeps(start_writer=ScriptedWriter(extracted(case))), REGISTRY
    )
    assert result["outcome"] == "completed", result
    assert all(c["status"] == "pass" for c in result["checks"]), result
    assert result["snapshots"]["initial"]["fields"]["budget"]["value"] is None
    assert result["snapshots"]["card:model.provider"]["fields"]["budget"]["source"] == "default"


def test_changed_answer_updates_latest_value_without_overwriting_initial():
    case = intake("C4-intake-change")
    writer = ScriptedWriter(
        extracted(case, budget=True),
        StartReply(changes=[StartChange(field="expected_users", value="301명", evidence="301명")]),
    )
    result = runner.run_case(case, "intake", JourneyDeps(start_writer=writer), REGISTRY)
    assert all(c["status"] == "pass" for c in result["checks"]), result
    assert result["snapshots"]["initial"]["fields"]["expected_users"]["value"] == "31"
    assert result["start_calls"] == 2


def test_hidden_value_is_not_the_answer_and_default_is_not_unknown():
    from benchmarks.evaluators.intake import evaluate

    checks = [{"id": "budget", "field": "budget", "policy": "unknown"}]
    for held in [
        dict(value="월 10만원", source="said", why="made up"),
        dict(value="무료로만", source="default", why="default"),
    ]:
        result = evaluate(checks, {"initial": {"fields": {"budget": held}}})
        assert result[0]["status"] == "fail"
    checks[0]["policy"] = "default"
    assert evaluate(checks, {"initial": {"fields": {}}})[0]["status"] == "fail"
    assert evaluate(checks, {})[0]["status"] == "not_run"


def test_unanswered_question_is_not_a_product_failure():
    case = intake("C4-intake-base")
    result = runner.run_case(
        case, "intake", JourneyDeps(start_writer=ScriptedWriter(StartReply())), REGISTRY
    )
    assert result["outcome"] == "scenario_unanswered"
    assert result["events"] == [{"type": "unanswered_question", "field": "goal"}]
    failed = runner.run_case(
        case,
        "intake",
        JourneyDeps(start_writer=ScriptedWriter(StartFailure(reason="test"))),
        REGISTRY,
    )
    assert failed["outcome"] == "product_error"


def test_mock_does_not_claim_extraction_quality():
    result = runner.run_case(intake("C4-intake-base"), "intake", JourneyDeps(), REGISTRY)
    assert result["outcome"] == "mock_unavailable"
    assert all(c["status"] == "not_run" for c in result["checks"])


def test_deadline_and_budget_abort_without_getting_swallowed(monkeypatch):
    import time

    def slow(*args):
        time.sleep(0.2)

    monkeypatch.setattr(runner, "run_intake", slow)
    result = runner.run_case(
        intake("C4-intake-base"), "intake", JourneyDeps(), REGISTRY, timeout_s=0.01
    )
    assert result["outcome"] == "timeout"
    monkeypatch.undo()
    writer = runner.CountingStartWriter(ScriptedWriter(), limit=0)
    result = runner.run_case(
        intake("C4-intake-base"), "intake", JourneyDeps(start_writer=writer), REGISTRY
    )
    assert result["outcome"] == "budget_exhausted" and writer.calls == 0


def test_step_limit_and_exceptions_are_reported(monkeypatch):
    case = intake("C4-intake-base")
    case["answers"] = {"goal": "목표를 다시 설명합니다"}
    monkeypatch.setattr(runner, "MAX_STEPS", 1)
    result = runner.run_case(
        case,
        "intake",
        JourneyDeps(start_writer=ScriptedWriter(StartReply(), StartReply())),
        REGISTRY,
    )
    assert result["outcome"] == "step_limit"
    result = runner.run_case(case, "intake", JourneyDeps(start_writer=ScriptedWriter()), REGISTRY)
    assert result["outcome"] == "product_error" and result["error_type"] in {
        "StopIteration",
        "RuntimeError",
    }


@pytest.mark.parametrize(
    "calls,fields,statuses,expected",
    [
        (1, [], [], True),
        (2, [], [], False),
        (1, [["invalid"]], [], False),
        (1, [], ["429"], False),
    ],
)
def test_single_draft_metric_never_counts_retry_success(
    monkeypatch, calls, fields, statuses, expected
):
    class Designer:
        def draft(self):
            pass

    def fake_blank(case, deps, registry):
        for _ in range(calls):
            deps.designer.draft()
        return {"design": {"source": "model"}}

    monkeypatch.setattr(runner, "run_blank", fake_blank)
    monkeypatch.setattr(
        runner,
        "log_findings",
        lambda _: {"failed_rules": [], "contract_fields": fields, "http_status": statuses},
    )
    result = runner.run_case(
        runner.load_cases(["C4"])[0], "blank", JourneyDeps(designer=Designer()), REGISTRY
    )
    assert result["single_draft_pass"] is expected
    assert result["http_attempts"] is None


def test_new_cases_validate_and_unknown_names_fail():
    from pydantic import ValidationError

    from benchmarks.evaluators.intake import IntakeCase

    case = intake("C4-intake-base")
    case["checks"][0]["policy"] = "unknown_or_default"
    with pytest.raises(ValidationError):
        IntakeCase.model_validate(case)
    with pytest.raises(ValueError):
        runner.load_cases(["does-not-exist"])


def test_followup_answer_is_selected_by_field_id():
    case = intake("C4-intake-base")
    case["answers"] = {"boundary": "검토한 다음에만 전달해야 합니다"}
    reply = extracted(case)
    reply.changes = [c for c in reply.changes if c.field != "boundary"]
    writer = ScriptedWriter(
        reply,
        StartReply(
            changes=[
                StartChange(field="boundary", value="검토 후 전달", evidence="검토한 다음에만")
            ]
        ),
    )
    result = runner.run_case(case, "intake", JourneyDeps(start_writer=writer), REGISTRY)
    assert result["outcome"] == "completed"
    assert result["events"] == [{"type": "answered", "field": "boundary"}]
    assert result["snapshots"]["initial"]["fields"]["boundary"]["value"] is None
    assert result["snapshots"]["final"]["fields"]["boundary"]["value"] == "검토 후 전달"


def test_new_design_fixed_selection_is_not_silently_substituted():
    case = {"evaluation": "design", "selection": {"data.checkpointer": "memory"}}
    card = {
        "card_id": "data.checkpointer",
        "recommendation": {"option_id": "postgres"},
        "options": [{"option": {"id": "postgres"}, "blocked_reason": None}],
    }
    with pytest.raises(runner.ScenarioUnanswered):
        runner._choose(case, card, REGISTRY)


def test_package_mismatch_is_detected():
    from app.journey.design import ServiceDesign
    from app.journey.package import package_zip

    from benchmarks.evaluators.design import design_checks

    case = runner.load_cases(["C4-design"])[0]
    result = runner.run_case(case, "flow", JourneyDeps(), REGISTRY)
    assert all(c["status"] == "pass" for c in result["checks"])
    design = ServiceDesign.model_validate(result["artifact"])
    checks = design_checks(
        design,
        package_zip({"BUILD.md": "wrong revision"}),
        REGISTRY,
        case["spec"]["idea"],
        case=case,
    )
    assert next(c for c in checks if c["id"] == "package_matches_revision")["status"] == "fail"


def test_real_calls_require_explicit_flag_and_intake_does_not_use_design_modes(monkeypatch):
    monkeypatch.setenv("APP_PROVIDER", "mock")
    monkeypatch.setenv("APP_DECIDER", "jev")
    with pytest.raises(SystemExit):
        runner.main(["--cases", "C4", "--runs", "1"])
    with pytest.raises(SystemExit):
        runner.main(["--mock", "--cases", "C4-intake-base", "--modes", "flow"])


def test_a_failed_start_call_keeps_its_reason():
    failure = StartFailure(reason="모델 호출 한도에 걸렸어요(HTTP 429). 잠시 후 다시 보내 주세요.")
    result = runner.run_case(
        intake("C4-intake-base"),
        "intake",
        JourneyDeps(start_writer=ScriptedWriter(failure)),
        REGISTRY,
    )

    assert result["start_attempts"][0]["source"] == "unavailable"
    assert "429" in result["start_attempts"][0]["reason"]


def test_the_report_names_the_model_that_writes_the_design():
    exaone = runner.Settings(
        _env_file=None, provider="exaone", exaone_api_key="test", gemini_model="g-lite"
    )
    gemini = runner.Settings(
        _env_file=None,
        provider="gemini",
        gemini_api_key="test",
        gemini_model="g-lite",
        gemini_design_model="g-big",
    )

    assert runner.design_model(exaone) == runner.EXAONE_MODEL
    assert runner.design_model(gemini) == "g-big"
