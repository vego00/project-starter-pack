"""The Codex model both loop roles use (judge and improvement agent), set once.

--ignore-user-config drops ~/.codex/config.toml, so the model has to be named here.
Chosen by the author on 2026-11-20: Astra 6.2 at low reasoning effort.
"""

CODEX_MODEL = "gpt-6.2-astra"
CODEX_EFFORT = "low"


def codex_model_args() -> list[str]:
    return ["-m", CODEX_MODEL, "-c", f"model_reasoning_effort={CODEX_EFFORT}"]
