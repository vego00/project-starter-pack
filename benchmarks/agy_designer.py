"""A designer that drafts through the Antigravity CLI (agy) instead of the Gemini API.

It sends what the product sends to Gemini: the design system prompt, the same user message and
the same output schema (provider_schema of DesignDraft). Two differences remain and are part of
every result: agy has no system prompt option, so the design system prompt goes first in the
message, and agy wraps every prompt in its own agent instructions (about 9.7k input tokens,
measured 2026-11-19). It runs in an empty folder with slash commands off and its sandbox on.
"""

import json
import subprocess
import tempfile
from pathlib import Path

from app.journey.design_generator import DesignAttempt, DesignDraft
from app.journey.llm import provider_schema
from app.journey.prompts import DESIGN_SYSTEM, design_user
from app.registry.loader import Registry

DEFAULT_MODEL = "gemini-3.8-flash-medium"
TIMEOUT_S = 600


class AgyCallFailed(RuntimeError):
    def __init__(self, reason: str, code: int | None = None):
        super().__init__(reason)
        self.code = code


def build_message(system: str, user: str) -> str:
    return f"SYSTEM INSTRUCTIONS:\n{system}\n\n---\n\n{user}"


class AgyDesigner:
    def __init__(
        self,
        registry: Registry,
        model: str = DEFAULT_MODEL,
        effort: str | None = None,
        timeout_s: int = TIMEOUT_S,
    ):
        self._registry = registry
        self.model = model
        self.effort = effort
        self._timeout = timeout_s
        self._schema = json.dumps(provider_schema(DesignDraft.model_json_schema()))
        # What the last call reported beyond the draft: agy can take several turns per call.
        self.last_call: dict = {}

    def draft(self, state, constraints, problems) -> DesignAttempt:
        message = build_message(
            DESIGN_SYSTEM, design_user(state, constraints, self._registry, problems)
        )
        with tempfile.TemporaryDirectory(prefix="agy-design-") as folder:
            schema = Path(folder, "schema.json")
            schema.write_text(self._schema, "utf-8")
            try:
                done = subprocess.run(
                    [
                        "agy",
                        "--print",
                        message,
                        "--model",
                        self.model,
                        "--output-format",
                        "json",
                        "--json-schema",
                        str(schema),
                        "--sandbox",
                        "--disable-slash-commands",
                        *(["--effort", self.effort] if self.effort else []),
                    ],  # fmt: skip
                    cwd=folder,
                    capture_output=True,
                    text=True,
                    timeout=self._timeout,
                )
            except subprocess.TimeoutExpired as exc:
                raise AgyCallFailed("timeout") from exc
        if done.returncode != 0:
            raise AgyCallFailed(f"exit {done.returncode}", done.returncode)
        try:
            result = json.loads(done.stdout)
        except json.JSONDecodeError as exc:
            raise AgyCallFailed("unreadable output") from exc
        if result.get("status") != "SUCCESS" or result.get("structured_output") is None:
            raise AgyCallFailed(f"status {result.get('status')}")
        usage = result.get("usage") or {}
        self.last_call = {
            "turns": result.get("num_turns"),
            "seconds": result.get("duration_seconds"),
            "thinking_tokens": usage.get("thinking_tokens"),
            "effort": self.effort,
        }
        # A draft that breaks the contract raises ValidationError here, like the Gemini client.
        draft = DesignDraft.model_validate(result["structured_output"])
        return DesignAttempt(
            draft=draft,
            model_id=f"agy:{self.model}",
            input_tokens=usage.get("input_tokens"),
            output_tokens=(usage.get("output_tokens") or 0) + (usage.get("thinking_tokens") or 0),
        )
