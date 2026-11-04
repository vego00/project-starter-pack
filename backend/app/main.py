import logging
from typing import Annotated
from uuid import uuid4

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from app.config import Settings
from app.providers.mock import MockProvider, StarterPackProvider
from app.schemas import ErrorResponse, GenerateRequest, GenerateResponse, StarterPack

logger = logging.getLogger(__name__)


def get_provider() -> StarterPackProvider:
    return MockProvider()


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="Project Starter Pack API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Do not return/log the original input, which may contain personal information.
        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "invalid_input",
                    "message": "문제는 앞뒤 공백을 제거한 뒤 10~3,000자, 참고 맥락은 2,000자 이내로 입력해 주세요.",
                }
            },
        )

    @app.get("/health")
    async def health():
        return {"status": "ok", "provider": settings.provider, "model_connected": False}

    @app.post(
        "/api/v1/starter-packs/generate",
        response_model=GenerateResponse,
        responses={
            422: {"model": ErrorResponse},
            502: {"model": ErrorResponse},
            503: {"model": ErrorResponse},
            504: {"model": ErrorResponse},
        },
    )
    async def generate(
        payload: GenerateRequest,
        provider: Annotated[StarterPackProvider, Depends(get_provider)],
    ):
        request_id = uuid4()
        try:
            pack = StarterPack.model_validate(await provider.generate_structured(payload))
        except TimeoutError:
            return JSONResponse(
                status_code=504,
                content={
                    "error": {
                        "code": "generation_timeout",
                        "message": "응답 시간이 초과되었습니다. 다시 시도해 주세요.",
                    }
                },
            )
        except ValidationError:
            return JSONResponse(
                status_code=502,
                content={
                    "error": {
                        "code": "invalid_output",
                        "message": "결과 형식을 확인하지 못했습니다. 다시 시도해 주세요.",
                    }
                },
            )
        except Exception:  # noqa: BLE001 - provider boundary; never expose input or secrets
            logger.error("Generation failed request_id=%s", request_id)
            return JSONResponse(
                status_code=503,
                content={
                    "error": {
                        "code": "generation_failed",
                        "message": "현재 결과를 만들 수 없습니다. 잠시 후 다시 시도해 주세요.",
                    }
                },
            )
        return GenerateResponse(
            request_id=request_id,
            provider="mock",
            is_mock=True,
            notice="모델 미연결 · 고정 템플릿 예시이며 실제 분석 결과가 아닙니다.",
            starter_pack=pack,
        )

    return app


app = create_app()
