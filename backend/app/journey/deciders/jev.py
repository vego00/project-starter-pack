"""Jev (TypeSafe AI) over either supported route. Both answer the same typed question."""

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

import httpx

from app.journey.deciders.base import DeciderBatch, DeciderQuestion, DeciderResult
from app.journey.prompts import project_context
from app.registry.loader import Registry

if TYPE_CHECKING:
    from app.journey.state import JourneyState

TIMEOUT_S = 10
QUESTION_KEY = "decision"
# The vendor advises an explicit way out when the labels might not cover every input.
NONE_FITS = "none_of_the_above"
NONE_FITS_MEANING = "주어진 정보로는 어느 선택지도 분명히 맞다고 판단할 수 없음"

JevRouteName = Literal["opencode", "vercel", "typesafe"]


def _parse_native(body: dict[str, Any], key: str) -> DeciderResult:
    answer = body["answers"][key]
    usage = body.get("usage", {})
    return DeciderResult(
        answer=answer["choice"],
        confidence=answer["confidence"],
        model_id=body.get("model"),
        input_tokens=usage.get("input_tokens"),
        output_tokens=usage.get("output_tokens"),
    )


def _parse_gateway(body: dict[str, Any], key: str) -> DeciderResult:
    answer = body["answers"][key]
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


@dataclass(frozen=True)
class JevRoute:
    base_url: str
    path: str
    default_model: str
    parse: Callable[[dict[str, Any], str], DeciderResult]
    extra_body: dict[str, Any] = field(default_factory=dict)


ROUTES: dict[JevRouteName, JevRoute] = {
    # Free for a limited time, with a usage cap and unstated retention: invented inputs only.
    "opencode": JevRoute(
        base_url="https://opencode.ai/inference/systemone",
        path="/v1/systemone",
        default_model="jev-1.13-free",
        parse=_parse_native,
    ),
    # Requires zero retention: without such a provider the request fails instead of downgrading.
    "vercel": JevRoute(
        base_url="https://ai-gateway.vercel.sh",
        path="/v1/evaluate",
        default_model="typesafe-ai/jev-1.14.0",
        parse=_parse_gateway,
        extra_body={"providerOptions": {"gateway": {"zeroDataRetention": True}}},
    ),
    # Paid direct API; same request and response shape as the OpenCode route.
    "typesafe": JevRoute(
        base_url="https://api.typesafe.ai",
        path="/v1/systemone",
        default_model="jev-latest",
        parse=_parse_native,
    ),
}


class JevDecider:
    name = "jev"

    def __init__(
        self,
        route: JevRouteName,
        registry: Registry,
        *,
        api_key: str | None = None,
        model: str | None = None,
        client: httpx.Client | None = None,
    ):
        self._route = ROUTES[route]
        self._registry = registry
        self._api_key = api_key
        self._model = model or self._route.default_model
        self._client = client or httpx.Client(base_url=self._route.base_url, timeout=TIMEOUT_S)

    def decide(self, state: "JourneyState", question: DeciderQuestion) -> DeciderResult:
        body = self._ask(state, {QUESTION_KEY: question})
        return self._route.parse(body, QUESTION_KEY)

    def decide_many(
        self, state: "JourneyState", questions: Sequence[DeciderQuestion]
    ) -> DeciderBatch:
        """One request; the API judges each key separately. Keys are positions, not ids."""
        keyed = {f"q{index}": question for index, question in enumerate(questions)}
        body = self._ask(state, keyed)
        results = {q.id: self._route.parse(body, key) for key, q in keyed.items()}
        # Model and usage belong to the request, so every result carries the same values.
        usage = next(iter(results.values()), DeciderResult(answer="", confidence=0))
        return DeciderBatch(
            results=results,
            model_id=usage.model_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
        )

    def _ask(self, state: "JourneyState", questions: dict[str, DeciderQuestion]) -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        response = self._client.post(
            self._route.path,
            headers=headers,
            content=json.dumps(
                {
                    "model": self._model,
                    "state": project_context(state, self._registry),
                    "questions": {
                        key: {
                            "type": "choice",
                            "instructions": question.text,
                            "criteria": {
                                **{c: question.criteria.get(c) for c in question.choices},
                                NONE_FITS: NONE_FITS_MEANING,
                            },
                        }
                        for key, question in questions.items()
                    },
                    **self._route.extra_body,
                },
                ensure_ascii=False,
            ).encode(),
        )
        response.raise_for_status()
        return response.json()
