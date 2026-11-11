"""Structured LLM calls behind one interface, so models can differ per agent (DiV P3)."""

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import httpx
from google import genai
from google.genai import types
from pydantic import BaseModel

TIMEOUT_MS = 20_000
MAX_ATTEMPTS = 2
RETRYABLE_STATUS = [429, 503]
MAX_OUTPUT_TOKENS = 2000


@dataclass(frozen=True)
class LLMResult[T: BaseModel]:
    output: T
    model_id: str
    input_tokens: int | None = None
    output_tokens: int | None = None


# Gemini rejects a schema of the design contract's size while these remain (400, 2026-11-05).
# The response is still checked against the full Pydantic schema, so no rule is lost.
_UNSENT_KEYWORDS = {
    "discriminator",
    "pattern",
    "maxLength",
    "minLength",
    "maxItems",
    "minItems",
    "minimum",
}


def provider_schema(node: Any) -> Any:
    if isinstance(node, list):
        return [provider_schema(item) for item in node]
    if not isinstance(node, dict):
        return node
    result: dict[str, Any] = {}
    for key, value in node.items():
        if key in {"properties", "$defs"}:
            result[key] = {name: provider_schema(item) for name, item in value.items()}
        elif key not in _UNSENT_KEYWORDS:
            result["anyOf" if key == "oneOf" else key] = provider_schema(value)
    return result


class StructuredLLM(Protocol):
    def generate[T: BaseModel](self, *, system: str, user: str, schema: type[T]) -> LLMResult[T]:
        """Raises on failure or on output that does not match `schema`."""
        ...


EXAONE_URL = "https://api.exaone.ai"
EXAONE_MODEL = "k-exaone_v2.5"
# The model always reasons and its reasoning counts toward max_tokens, so the cap is higher.
EXAONE_MAX_TOKENS = 8000
_JSON_RULE = (
    "응답은 아래 JSON 스키마를 따르는 JSON 객체 하나만 씁니다. "
    "설명, 머리말, 코드 블록 표시 없이 JSON만 씁니다.\nSCHEMA:\n"
)
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
# The free tier allows one call a second; a 429 says how long to wait.
MAX_RETRY_WAIT_S = 5.0


def _retry_after(response: httpx.Response) -> float:
    headers = response.headers
    try:
        if "retry-after-ms" in headers:
            wait = float(headers["retry-after-ms"]) / 1000
        else:
            wait = float(headers.get("retry-after", 1))
    except ValueError:
        wait = 1.0
    return min(max(wait, 0.0), MAX_RETRY_WAIT_S)


class ExaoneLLM:
    """K-EXAONE over its OpenAI-compatible chat API, which documents no structured output:
    the schema goes in the prompt and the answer is checked against the full Pydantic schema."""

    def __init__(
        self,
        api_key: str,
        model: str = EXAONE_MODEL,
        client: httpx.Client | None = None,
        *,
        timeout_ms: int = TIMEOUT_MS,
        max_output_tokens: int = EXAONE_MAX_TOKENS,
        reasoning_effort: Literal["low", "high", "max"] = "low",
    ):
        self._api_key = api_key
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._effort = reasoning_effort
        self._client = client or httpx.Client(base_url=EXAONE_URL, timeout=timeout_ms / 1000)

    def generate[T: BaseModel](self, *, system: str, user: str, schema: type[T]) -> LLMResult[T]:
        shape = json.dumps(schema.model_json_schema(), ensure_ascii=False)
        body = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": f"{system}\n\n{_JSON_RULE}{shape}"},
                {"role": "user", "content": user},
            ],
            "max_tokens": self._max_output_tokens,
            "reasoning_effort": self._effort,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"}
        for attempt in range(MAX_ATTEMPTS):
            response = self._client.post("/v1/chat/completions", json=body, headers=headers)
            if response.status_code not in RETRYABLE_STATUS or attempt == MAX_ATTEMPTS - 1:
                break
            time.sleep(_retry_after(response))
        response.raise_for_status()
        data = response.json()
        text = data["choices"][0]["message"]["content"] or ""
        usage = data.get("usage") or {}
        return LLMResult(
            output=schema.model_validate_json(_FENCE.sub("", text.strip())),
            model_id=data.get("model") or self._model,
            input_tokens=usage.get("prompt_tokens"),
            output_tokens=usage.get("completion_tokens"),
        )


class GeminiLLM:
    """Uses `generate_content`, which keeps no conversation state on the provider side."""

    def __init__(
        self,
        api_key: str,
        model: str,
        client: genai.Client | None = None,
        *,
        timeout_ms: int = TIMEOUT_MS,
        max_output_tokens: int = MAX_OUTPUT_TOKENS,
    ):
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=timeout_ms,
                retry_options=types.HttpRetryOptions(
                    attempts=MAX_ATTEMPTS, http_status_codes=RETRYABLE_STATUS
                ),
            ),
        )

    def generate[T: BaseModel](self, *, system: str, user: str, schema: type[T]) -> LLMResult[T]:
        response = self._client.models.generate_content(
            model=self._model,
            contents=user,
            config=types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=provider_schema(schema.model_json_schema()),
                max_output_tokens=self._max_output_tokens,
            ),
        )
        usage = response.usage_metadata
        return LLMResult(
            output=schema.model_validate_json(response.text or ""),
            model_id=response.model_version or self._model,
            input_tokens=usage.prompt_token_count if usage else None,
            output_tokens=usage.candidates_token_count if usage else None,
        )
