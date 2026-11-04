"""Structured LLM calls behind one interface, so models can differ per agent (DiV P3)."""

from dataclasses import dataclass
from typing import Protocol

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


class StructuredLLM(Protocol):
    def generate[T: BaseModel](self, *, system: str, user: str, schema: type[T]) -> LLMResult[T]:
        """Raises on failure or on output that does not match `schema`."""
        ...


class GeminiLLM:
    """Uses `generate_content`, which keeps no conversation state on the provider side."""

    def __init__(self, api_key: str, model: str, client: genai.Client | None = None):
        self._model = model
        self._client = client or genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=TIMEOUT_MS,
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
                response_json_schema=schema.model_json_schema(),
                max_output_tokens=MAX_OUTPUT_TOKENS,
            ),
        )
        usage = response.usage_metadata
        return LLMResult(
            output=schema.model_validate_json(response.text or ""),
            model_id=response.model_version or self._model,
            input_tokens=usage.prompt_token_count if usage else None,
            output_tokens=usage.candidates_token_count if usage else None,
        )
