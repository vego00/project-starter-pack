"""Structured LLM calls behind one interface, so models can differ per agent (DiV P3)."""

from dataclasses import dataclass
from typing import Any, Protocol

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
