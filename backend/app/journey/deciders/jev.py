"""Jev (TypeSafe AI) through Vercel AI Gateway's Decision API: POST /v1/evaluate."""

import json
from typing import TYPE_CHECKING

import httpx

from app.journey.deciders.base import DeciderQuestion, DeciderResult
from app.journey.prompts import project_context
from app.registry.loader import Registry

if TYPE_CHECKING:
    from app.journey.state import JourneyState

API_BASE = "https://ai-gateway.vercel.sh"
TIMEOUT_S = 10
QUESTION_KEY = "decision"
# The vendor advises an explicit way out when the labels might not cover every input.
NONE_FITS = "none_of_the_above"
NONE_FITS_MEANING = "주어진 정보로는 어느 선택지도 분명히 맞다고 판단할 수 없음"
# The project idea is user data. Without a zero-retention provider the request fails instead.
GATEWAY_OPTIONS = {"gateway": {"zeroDataRetention": True}}


class JevDecider:
    name = "jev"

    def __init__(
        self, api_key: str, model: str, registry: Registry, client: httpx.Client | None = None
    ):
        self._api_key = api_key
        self._model = model
        self._registry = registry
        self._client = client or httpx.Client(base_url=API_BASE, timeout=TIMEOUT_S)

    def decide(self, state: "JourneyState", question: DeciderQuestion) -> DeciderResult:
        criteria = {choice: question.criteria.get(choice) for choice in question.choices}
        response = self._client.post(
            "/v1/evaluate",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            content=json.dumps(
                {
                    "model": self._model,
                    "state": project_context(state, self._registry),
                    "questions": {
                        QUESTION_KEY: {
                            "type": "choice",
                            "instructions": question.text,
                            "criteria": {**criteria, NONE_FITS: NONE_FITS_MEANING},
                        }
                    },
                    "providerOptions": GATEWAY_OPTIONS,
                },
                ensure_ascii=False,
            ).encode(),
        )
        response.raise_for_status()
        body = response.json()
        answer = body["answers"][QUESTION_KEY]
        choice = answer["choice"]
        usage = body.get("usage", {})
        return DeciderResult(
            answer=choice,
            # This API documents per-option probabilities, so the chosen one is the gate value.
            confidence=answer["probabilities"][choice],
            model_id=body.get("model"),
            input_tokens=usage.get("inputTokens"),
            output_tokens=usage.get("outputTokens"),
        )
