"""The FastAPI app (spec 06, story #134). Routers are thin: they check the request, call
`revint.api.service` and shape the answer. They hold no SQL and never import duckdb.

All paths are under /api/v1. Errors have one body, {"error": {"code", "message"}}: 400 for a
bad parameter, 404 for an unknown id, 503 when the warehouse or the opportunity tables are not
built. CORS allows only `api.cors_origins`.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from revint.api import service
from revint.api.models import (
    DefinitionsResponse,
    ErrorResponse,
    HealthResponse,
    OpportunitiesResponse,
    OpportunityDetail,
    OverviewResponse,
)
from revint.config import Settings, load_settings

PREFIX = "/api/v1"
_ERRORS: dict[int | str, dict[str, Any]] = {
    400: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def create_app(settings: Settings | None = None) -> FastAPI:
    """The app for `settings` (the committed settings by default)."""
    settings = settings or load_settings()
    app = FastAPI(
        title="Revenue intelligence API",
        version="0.1.0",
        description="Read-only API over the opportunity tables (spec 06).",
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.api.cors_origins),
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )

    @app.exception_handler(service.NotReadyError)
    async def _not_ready(_request: Request, exc: service.NotReadyError) -> JSONResponse:
        return _error(503, "not_ready", str(exc))

    @app.exception_handler(service.NotFoundError)
    async def _not_found(_request: Request, _exc: service.NotFoundError) -> JSONResponse:
        return _error(404, "not_found", "no opportunity with that id")

    @app.exception_handler(RequestValidationError)
    async def _invalid(_request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p not in ("query", "path"))
        return _error(400, "bad_request", f"invalid {where or 'request'}: {first.get('msg', '')}")

    router = APIRouter(prefix=PREFIX)

    @router.get("/health", response_model=HealthResponse)
    def health() -> dict[str, Any]:
        return service.health(settings)

    @router.get("/definitions", response_model=DefinitionsResponse)
    def definitions() -> dict[str, Any]:
        return {"definitions": service.definitions()}

    @router.get("/overview", response_model=OverviewResponse, responses=_ERRORS)
    def overview() -> dict[str, Any]:
        return service.overview(settings)

    @router.get("/opportunities", response_model=OpportunitiesResponse, responses=_ERRORS)
    def opportunities(
        type: Annotated[
            Literal["dormancy", "recovery", "whitespace", "crosssell"] | None, Query()
        ] = None,
        priority: Annotated[Literal["High", "Medium", "Low"] | None, Query()] = None,
        confidence: Annotated[Literal["High", "Medium", "Low"] | None, Query()] = None,
        branch: Annotated[str | None, Query(max_length=200)] = None,
        channel: Annotated[str | None, Query(max_length=200)] = None,
        page: Annotated[int, Query(ge=1)] = 1,
        page_size: Annotated[int | None, Query(ge=1)] = None,
        sort: Annotated[Literal["rank", "score", "value_high"], Query()] = "rank",
    ) -> dict[str, Any] | JSONResponse:
        size = page_size or settings.api.page_size_default
        if size > settings.api.page_size_max:
            return _error(
                400, "bad_request", f"page_size must be at most {settings.api.page_size_max}"
            )
        filters = service.Filters(type, priority, confidence, branch, channel)
        return service.opportunities(settings, filters, page, size, sort)

    @router.get("/opportunities/{opp_id}", response_model=OpportunityDetail, responses=_ERRORS)
    def opportunity(opp_id: str) -> dict[str, Any]:
        return service.opportunity(settings, opp_id)

    app.include_router(router)
    return app
