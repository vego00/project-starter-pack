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
