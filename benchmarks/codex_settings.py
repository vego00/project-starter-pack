"""The Codex models the loop roles use, set once.

--ignore-user-config drops ~/.codex/config.toml, so the models have to be named here.
Improvement agent: Astra 6.2 at low reasoning effort (author, 2026-11-20).
Judge: GPT-6.2 Sol, the lighter model (author, 2026-11-23). Astra 6.2 low allowed only about 30
judge calls per usage window on the author's plan, so a loop run stopped halfway. Sol rejects
effort "none" (it takes low, medium, high, xhigh, max), so the judge uses its lowest, low.
"""

CODEX_MODEL = "gpt-6.2-astra"
CODEX_EFFORT = "low"
JUDGE_MODEL = "gpt-6.2-sol"
JUDGE_EFFORT = "low"


def codex_model_args(model: str = CODEX_MODEL, effort: str = CODEX_EFFORT) -> list[str]:
    return ["-m", model, "-c", f"model_reasoning_effort={effort}"]
