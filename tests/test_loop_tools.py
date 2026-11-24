"""The improvement agent's guard keeps a Codex change inside the prompt text it may edit."""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("improve", ROOT / "benchmarks" / "improve.py")
improve = importlib.util.module_from_spec(spec)
spec.loader.exec_module(improve)

PROMPTS = (ROOT / improve.PROMPTS).read_text("utf-8")
GENERATOR = (ROOT / improve.GENERATOR).read_text("utf-8")


def test_editing_the_design_prompt_and_version_is_in_bounds():
    changed = PROMPTS.replace("설계 방법:", "설계 방법(고침):", 1).replace(
        f'DESIGN_VERSION = "{improve.version_of(PROMPTS)}"', 'DESIGN_VERSION = "design-loop-r1"'
    )

    assert improve.guard(improve.PROMPTS, PROMPTS, changed) == []
    assert improve.version_of(changed) == "design-loop-r1"


def test_editing_any_other_prompt_or_function_is_caught():
    other = PROMPTS.replace('GCB_VERSION = "gcb-v1"', 'GCB_VERSION = "gcb-v9"')
    added = PROMPTS + "\nEXTRA = 1\n"
    function = PROMPTS.replace("def design_user(", "def design_user_renamed(", 1)

    assert improve.guard(improve.PROMPTS, PROMPTS, other) == ["GCB_VERSION"]
    assert improve.guard(improve.PROMPTS, PROMPTS, added) == ["EXTRA"]
    assert "design_user" in improve.guard(improve.PROMPTS, PROMPTS, function)


def test_only_fix_hints_may_change_in_the_generator():
    hints = GENERATOR.replace("on_exceeded를", "on_exceeded(한도 출구)를", 1)
    attempts = GENERATOR.replace("MAX_ATTEMPTS = 2", "MAX_ATTEMPTS = 5", 1)

    assert improve.guard(improve.GENERATOR, GENERATOR, hints) == []
    assert improve.guard(improve.GENERATOR, GENERATOR, attempts) == ["MAX_ATTEMPTS"]


loop_spec = importlib.util.spec_from_file_location("loop", ROOT / "benchmarks" / "loop.py")
loop = importlib.util.module_from_spec(loop_spec)
loop_spec.loader.exec_module(loop)


def _m(model, rules=None, single=0):
    return {"runs": 3, "model": model, "single": single, "rules": rules or {}}


def test_fewer_rejections_by_two_are_kept_and_one_is_not():
    best = {"A": _m(3, {"io.unconnected": 2}), "B": _m(3, {"형식:state_fields.0": 1})}

    assert loop.decide(best, {"A": _m(3), "B": _m(3, {"형식:state_fields.0": 1})})[0] is True
    assert loop.decide(best, {"A": _m(3, {"io.unconnected": 1}), "B": _m(3, {"x": 1})})[0] is False


def test_fewer_designs_or_single_passes_revert_even_with_fewer_rejections():
    best = {"A": _m(3, {"io.unconnected": 3}, single=2)}

    assert loop.decide(best, {"A": _m(2, single=2)})[0] is False
    assert loop.decide(best, {"A": _m(3, single=1)})[0] is False


def test_more_sending_before_approval_always_reverts():
    best = {"A": _m(3, {"io.unconnected": 4})}
    worse = {"A": _m(3, {loop.CORE_RULE: 1})}

    assert loop.decide(best, worse)[0] is False


def test_a_failed_measurement_is_not_judged():
    assert loop.decide({"A": _m(1)}, {"A": {"failed": True}})[0] is False


def test_two_measurements_of_a_kept_prompt_are_averaged():
    first = {"A": _m(3, {"io.unconnected": 2}, single=3)}
    second = {"A": _m(2, {"io.unconnected": 4, "x": 1}, single=1)}

    mean = loop.average(first, second)["A"]

    assert mean["model"] == 2.5 and mean["single"] == 2
    assert mean["rules"] == {"io.unconnected": 3, "x": 0.5}


def _j(score, model=3, single=3, rules=None):
    return {**_m(model, rules, single), "judge": score}


def test_a_judge_gain_of_five_points_is_kept_and_less_is_not():
    best = {"A": _j(0.60), "B": _j(0.70)}

    assert loop.decide(best, {"A": _j(0.66), "B": _j(0.74)})[0]
    assert not loop.decide(best, {"A": _j(0.62), "B": _j(0.72)})[0]


def test_with_judge_scores_floors_still_revert():
    best = {"A": _j(0.5, single=3), "B": _j(0.5, single=3)}

    assert not loop.decide(best, {"A": _j(0.9, model=2), "B": _j(0.9)})[0]
    assert not loop.decide(best, {"A": _j(0.9, rules={loop.CORE_RULE: 1}), "B": _j(0.9)})[0]
    assert loop.decide(best, {"A": _j(0.9, single=2), "B": _j(0.9, single=2)})[0]
    assert not loop.decide(best, {"A": _j(0.9, single=1), "B": _j(0.9, single=2)})[0]


def test_a_case_the_judge_could_not_score_is_not_decided():
    best = {"A": _j(0.5), "B": _j(0.5)}

    keep, why = loop.decide(best, {"A": _j(0.9), "B": _j(None)})

    assert not keep and "채점" in why


def test_judge_scores_average_per_case_and_keep_notes_below_full_marks(tmp_path):
    import json

    def score(*points):
        return {"result": {"scores": [
            {"criterion": i, "score": p, "quote": "", "reason": f"이유{i}"}
            for i, p in enumerate(points, 1)]}}  # fmt: skip

    key = {"J-1": "r0-C1-1", "J-2": "r0-C1-2", "J-3": "r0-C4-design-1", "J-4": "r0-C8-1"}
    (tmp_path / "judge-key.json").write_text(json.dumps(key))
    (tmp_path / "judge-J-1.json").write_text(json.dumps(score(2, 2)))
    (tmp_path / "judge-J-2.json").write_text(json.dumps(score(2, 0)))
    (tmp_path / "judge-J-3.json").write_text(json.dumps(score(1, 1)))
    (tmp_path / "judge-J-4.json").write_text(json.dumps({"error": "exit 1"}))

    scored = loop.judge_scores(tmp_path)

    assert scored["C1"]["score"] == 0.75
    assert scored["C4-design"]["score"] == 0.5
    assert "C8" not in scored
    assert scored["C1"]["notes"] == ["기준 2 (0/2): 이유2"]


def test_questions_the_builder_should_not_have_to_ask_reach_the_improver(tmp_path):
    import json

    questions = [{"question": "기획서 양식은?", "kind": "decide_before_build"},
                 {"question": "API 키를 .env에 넣어 주세요", "kind": "human_only"}]  # fmt: skip
    result = {"result": {"scores": [{"criterion": 1, "score": 2, "quote": "", "reason": ""}],
                         "builder_questions": questions}}  # fmt: skip
    (tmp_path / "judge-key.json").write_text(json.dumps({"J-1": "r0-C1-1"}))
    (tmp_path / "judge-J-1.json").write_text(json.dumps(result))

    assert loop.judge_scores(tmp_path)["C1"]["notes"] == ["빌더가 물을 질문: 기획서 양식은?"]


def test_averaging_keeps_the_judge_score():
    mean = loop.average({"A": _j(0.6)}, {"A": _j(0.8)})["A"]

    assert abs(mean["judge"] - 0.7) < 1e-9


def _judge_module():
    found = importlib.util.spec_from_file_location("judge", ROOT / "benchmarks" / "judge.py")
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


def _validator_fixture():
    path = ROOT / "backend" / "tests" / "test_design_validator.py"
    found = importlib.util.spec_from_file_location("validator_fixture", path)
    module = importlib.util.module_from_spec(found)
    found.loader.exec_module(module)
    return module


def test_the_judge_sees_common_criteria_after_the_case_and_the_build_files():
    judge = _judge_module()
    design = _validator_fixture().valid_design()
    design["provenance"]["generated_at"] = design["provenance"]["generated_at"].isoformat()
    case = {"spec": {"idea": "강의 자료에서 답을 찾는다"}, "selection": {},
            "human_review": ["출처를 붙인다"]}  # fmt: skip

    prompt = judge.build_prompt(case, design)

    assert "1. 출처를 붙인다" in prompt
    assert f"2. {judge.COMMON_CRITERIA[0]}" in prompt
    for name in judge.BUILD_FILES:
        assert f"### {name}\n\n~~~~\n" in prompt
    assert "design-v1" not in prompt and "test-model" not in prompt
