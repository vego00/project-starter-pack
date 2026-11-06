import logging
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from langgraph.types import Checkpointer
from pydantic import BaseModel

from app.config import Settings
from app.journey.design import ServiceDesign
from app.journey.persistence import open_checkpointer
from app.journey.service import JourneyError, JourneyService, JourneyView
from app.journey.services import JourneyDeps, build_deps
from app.journey.state import JourneyAction, ProjectSpec
from app.registry.loader import Registry, load_registry

logger = logging.getLogger(__name__)


class ErrorDetail(BaseModel):
    code: str
    message: str


class ErrorResponse(BaseModel):
    error: ErrorDetail


class ActionRequest(BaseModel):
    revision: int
    action: JourneyAction


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _guarded[T](journey_id: UUID | None, run: Callable[[], T]) -> T:
    try:
        return run()
    except JourneyError:
        raise
    except Exception as exc:  # noqa: BLE001 - never expose input or internals to the client
        logger.error("Journey step failed journey_id=%s type=%s", journey_id, type(exc).__name__)
        raise JourneyError(
            503, "journey_failed", "지금은 처리하지 못했어요. 잠시 후 다시 시도해 주세요."
        ) from None


def get_journeys(request: Request) -> JourneyService:
    service = request.app.state.journeys
    if service is None:
        raise JourneyError(
            503, "persistence_unavailable", "저장소가 연결되어 있지 않아 여정을 시작할 수 없어요."
        )
    return service


Journeys = Annotated[JourneyService, Depends(get_journeys)]
ERROR_RESPONSES = {status: {"model": ErrorResponse} for status in (404, 409, 422, 503)}


def create_app(
    settings: Settings | None = None,
    *,
    checkpointer: Checkpointer = None,
    deps: JourneyDeps | None = None,
    registry: Registry | None = None,
) -> FastAPI:
    settings = settings or Settings()
    registry = registry or load_registry()
    deps = deps or build_deps(settings, registry)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if checkpointer is not None:
            app.state.journeys = JourneyService(registry, checkpointer, deps)
            yield
        elif settings.database_url is not None:
            with open_checkpointer(settings.database_url.get_secret_value()) as saver:
                app.state.journeys = JourneyService(registry, saver, deps)
                yield
        else:
            app.state.journeys = None
            yield

    app = FastAPI(title="Project Starter Pack API", version="0.2.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        # Do not return/log the original input, which may contain personal information.
        return _error(422, "invalid_input", "입력 내용을 확인해 주세요.")

    @app.exception_handler(JourneyError)
    async def journey_error(request: Request, exc: JourneyError):
        return _error(exc.status, exc.code, exc.message)

    @app.get("/health")
    def health(request: Request):
        return {
            "status": "ok",
            "provider": settings.provider,
            "decider": settings.decider,
            # Configured, not proven to work: no model is called for a health check.
            "model_configured": settings.provider != "mock",
            "journeys_available": getattr(request.app.state, "journeys", None) is not None,
        }

    # Sync routes on purpose: FastAPI runs them in a thread pool and the graph is synchronous.
    @app.post(
        "/api/v1/journeys", status_code=201, response_model=JourneyView, responses=ERROR_RESPONSES
    )
    def create_journey(spec: ProjectSpec, journeys: Journeys):
        return _guarded(None, lambda: journeys.start(spec))

    @app.get("/api/v1/journeys/{journey_id}", response_model=JourneyView, responses=ERROR_RESPONSES)
    def get_journey(journey_id: UUID, journeys: Journeys):
        return _guarded(journey_id, lambda: journeys.get(journey_id))

    @app.post(
        "/api/v1/journeys/{journey_id}/decisions",
        response_model=JourneyView,
        responses=ERROR_RESPONSES,
    )
    def act_on_journey(journey_id: UUID, payload: ActionRequest, journeys: Journeys):
        return _guarded(
            journey_id, lambda: journeys.act(journey_id, payload.revision, payload.action)
        )

    @app.get("/api/v1/journeys/{journey_id}/summary.md", responses=ERROR_RESPONSES)
    def get_summary(journey_id: UUID, journeys: Journeys):
        document = _guarded(journey_id, lambda: journeys.summary(journey_id))
        return Response(
            content=document,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": 'attachment; filename="decision-summary.md"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get(
        "/api/v1/journeys/{journey_id}/design",
        response_model=ServiceDesign,
        responses=ERROR_RESPONSES,
    )
    def get_design(journey_id: UUID, journeys: Journeys):
        return _guarded(journey_id, lambda: journeys.design(journey_id))

    @app.get("/api/v1/journeys/{journey_id}/package.zip", responses=ERROR_RESPONSES)
    def get_package(journey_id: UUID, journeys: Journeys):
        archive = _guarded(journey_id, lambda: journeys.package(journey_id))
        return Response(
            content=archive,
            media_type="application/zip",
            headers={
                "Content-Disposition": 'attachment; filename="starter-pack.zip"',
                "X-Content-Type-Options": "nosniff",
            },
        )

    return app


app = create_app()
