"""Calls each configured model once and prints metadata only. Spends a small amount of credit."""

import sys
import time
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import httpx  # noqa: E402
from app.config import Settings  # noqa: E402
from app.journey.deciders.base import DeciderQuestion  # noqa: E402
from app.journey.llm import GeminiLLM  # noqa: E402
from app.journey.services import build_deps  # noqa: E402
from app.journey.state import JourneyState, ProjectSpec  # noqa: E402
from app.registry.loader import load_registry  # noqa: E402
from pydantic import BaseModel  # noqa: E402

IDEA = "강의 자료를 찾아 질문에 답하고 출처를 알려주는 멀티 에이전트 서비스"


class Ping(BaseModel):
    answer: str


def _error_type(response: httpx.Response) -> str:
    try:
        error = response.json().get("error", {})
        return str(error.get("type") or error.get("code") or "") if isinstance(error, dict) else ""
    except ValueError:
        return ""


def check(name, call) -> bool:
    started = time.perf_counter()
    try:
        detail = call()
    except httpx.HTTPStatusError as exc:
        # Status and error type only: the body can echo request content.
        print(f"{name}: FAILED HTTP {exc.response.status_code} {_error_type(exc.response)}")
        return False
    except Exception as exc:  # noqa: BLE001 - report the failure type and keep checking the rest
        print(f"{name}: FAILED {type(exc).__name__}")
        return False
    print(f"{name}: OK {(time.perf_counter() - started) * 1000:.0f}ms {detail}")
    return True


def main() -> int:
    settings = Settings()
    results = []
    if settings.gemini_api_key and settings.gemini_model:
        llm = GeminiLLM(settings.gemini_api_key.get_secret_value(), settings.gemini_model)

        def gemini():
            result = llm.generate(system="짧게 답하세요.", user="1+1은?", schema=Ping)
            return f"model={result.model_id} in={result.input_tokens} out={result.output_tokens}"

        results.append(check("gemini", gemini))
    else:
        print("gemini: SKIPPED (APP_GEMINI_API_KEY or APP_GEMINI_MODEL is empty)")
    if settings.decider == "jev" or settings.jev_route == "opencode" or settings.ai_gateway_api_key:
        state = JourneyState(journey_id=uuid4(), project_spec=ProjectSpec(idea=IDEA))
        decider = build_deps(
            settings.model_copy(update={"decider": "jev"}), load_registry()
        ).decider
        question = DeciderQuestion(
            id="smoke",
            text="이 프로젝트에 문서 검색이 필요한가요?",
            choices=("yes", "no"),
            criteria={"yes": "필요함", "no": "필요하지 않음"},
        )

        def jev():
            result = decider.decide(state, question)
            return (
                f"model={result.model_id} answer={result.answer} "
                f"confidence={result.confidence:.2f} in={result.input_tokens}"
            )

        results.append(check(f"jev[{settings.jev_route}]", jev))
    else:
        print("jev: SKIPPED (route needs a key)")
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
