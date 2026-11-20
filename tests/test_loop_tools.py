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
