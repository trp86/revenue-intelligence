"""The FastAPI app (spec 06, story #134). Routers are thin: they check the request, call
`revint.api.service` and shape the answer. They hold no SQL and never import duckdb.

All paths are under /api/v1. Errors have one body, {"error": {"code", "message"}}: 400 for a
bad parameter, 404 for an unknown id, 503 when the warehouse or the opportunity tables are not
built. CORS allows only `api.cors_origins`, with credentials (the session cookie).

Since story #191 every endpoint except /health and /auth/login needs a signed-in session
(401 "not_signed_in" otherwise); see revint.auth and revint.api.auth.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from revint import auth as users
from revint.api import auth, briefs, service
from revint.api.models import (
    BriefResponse,
    DefinitionsResponse,
    ErrorResponse,
    HealthResponse,
    LoginRequest,
    OpportunitiesResponse,
    OpportunityDetail,
    OverviewResponse,
    UserResponse,
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
        allow_credentials=True,  # the session cookie (story #191)
        allow_methods=["GET", "POST"],
        allow_headers=["*"],
    )
    store = users.SessionStore(
        session_hours=settings.auth.session_hours,
        max_attempts=settings.auth.max_attempts,
        lockout_minutes=settings.auth.lockout_minutes,
    )

    @app.exception_handler(auth.NotSignedInError)
    async def _not_signed_in(_request: Request, _exc: auth.NotSignedInError) -> JSONResponse:
        return _error(401, "not_signed_in", "sign in to use the app")

    @app.exception_handler(service.NotReadyError)
    async def _not_ready(_request: Request, exc: service.NotReadyError) -> JSONResponse:
        return _error(503, "not_ready", str(exc))

    @app.exception_handler(service.NotFoundError)
    async def _not_found(_request: Request, exc: service.NotFoundError) -> JSONResponse:
        if isinstance(exc, service.NoBriefError):
            return _error(404, "no_brief", "this opportunity has no AI brief yet")
        return _error(404, "not_found", "no opportunity with that id")

    @app.exception_handler(briefs.AiDisabledError)
    async def _ai_disabled(_request: Request, _exc: briefs.AiDisabledError) -> JSONResponse:
        return _error(503, "ai_disabled", "AI briefs are turned off; the evidence is complete")

    @app.exception_handler(briefs.AiUnavailableError)
    async def _ai_unavailable(_request: Request, exc: briefs.AiUnavailableError) -> JSONResponse:
        return _error(503, "ai_unavailable", f"the AI brief is not available now ({exc})")

    @app.exception_handler(briefs.AiFailedError)
    async def _ai_failed(_request: Request, exc: briefs.AiFailedError) -> JSONResponse:
        return _error(503, "ai_unavailable", str(exc))

    @app.exception_handler(RequestValidationError)
    async def _invalid(_request: Request, exc: RequestValidationError) -> JSONResponse:
        first = exc.errors()[0] if exc.errors() else {}
        where = ".".join(str(p) for p in first.get("loc", ()) if p not in ("query", "path"))
        return _error(400, "bad_request", f"invalid {where or 'request'}: {first.get('msg', '')}")

    def signed_in(request: Request) -> str:
        # looked up on the module at call time, so the tests can stand in a user
        return auth.require_user(request, store)

    public = APIRouter(prefix=PREFIX)
    router = APIRouter(prefix=PREFIX, dependencies=[Depends(signed_in)])

    @public.get("/health", response_model=HealthResponse)
    def health() -> dict[str, Any]:
        return service.health(settings)

    @public.post(
        "/auth/login",
        response_model=UserResponse,
        responses={401: {"model": ErrorResponse}, 429: {"model": ErrorResponse}},
    )
    def login(body: LoginRequest, response: Response) -> dict[str, Any] | JSONResponse:
        name = body.username.strip().lower()
        if store.is_locked(name):
            return _error(429, "locked", "Too many failed attempts. Try again later.")
        if not users.verify(settings.paths.users, name, body.password):
            store.record_failure(name)
            return _error(401, "bad_credentials", "User name or password is incorrect.")
        response.set_cookie(
            auth.COOKIE,
            store.start(name),
            max_age=settings.auth.session_hours * 3600,
            httponly=True,
            secure=settings.auth.cookie_secure,
            samesite=settings.auth.cookie_samesite,
            path="/",
        )
        return {"user": name}

    @public.post("/auth/logout")
    def logout(request: Request, response: Response) -> dict[str, bool]:
        store.end(request.cookies.get(auth.COOKIE))
        response.delete_cookie(
            auth.COOKIE,
            path="/",
            secure=settings.auth.cookie_secure,
            samesite=settings.auth.cookie_samesite,
            httponly=True,
        )
        return {"ok": True}

    @router.get("/auth/me", response_model=UserResponse)
    def me(request: Request) -> dict[str, str]:
        return {"user": signed_in(request)}

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

    @router.get("/opportunities/{opp_id}/brief", response_model=BriefResponse, responses=_ERRORS)
    def brief(opp_id: str) -> dict[str, Any]:
        return briefs.latest_brief(settings, opp_id)

    @router.post("/opportunities/{opp_id}/brief", response_model=BriefResponse, responses=_ERRORS)
    def generate_brief(opp_id: str, regenerate: bool = False) -> dict[str, Any]:
        # regenerate=true skips the cache and always calls Gemini (story #181)
        return briefs.generate_brief(settings, opp_id, regenerate=regenerate)

    app.include_router(public)
    app.include_router(router)
    return app
