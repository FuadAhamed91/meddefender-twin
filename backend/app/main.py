"""Application factory. Run with ``uvicorn app.main:create_app --factory``."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api import (
    routes_auth,
    routes_events,
    routes_incidents,
    routes_security,
    routes_simulation,
    routes_telemetry,
    routes_twin,
    ws,
)
from app.core.clock import Clock, SystemClock
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.db.session import build_engine, build_session_factory
from app.services.context import AppServices
from app.services.flow_analysis import FlowAnalysis
from app.services.ingestion import IngestionPipeline
from app.simulator.runtime import SimulationRuntime
from app.simulator.world import WorldCommandSink

logger = logging.getLogger("meddefender")
_CORRELATION_RE = re.compile(r"^[A-Za-z0-9-]{8,64}$")

HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "AUTHENTICATION_REQUIRED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
    413: "PAYLOAD_TOO_LARGE",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
}


def _error(
    status: int, code: str, message: str, request: Request, details: Any = None
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details,
                "correlation_id": getattr(request.state, "correlation_id", None),
            }
        },
    )


def create_app(
    settings: Settings | None = None,
    *,
    services: AppServices | None = None,
    clock: Clock | None = None,
    start_background: bool = True,
) -> FastAPI:
    settings = settings or (services.settings if services else get_settings())
    settings.assert_production_safe()
    logging.basicConfig(level=settings.log_level)

    def wire(app: FastAPI, svc: AppServices) -> SimulationRuntime:
        pipeline = IngestionPipeline(
            svc, command_sink=WorldCommandSink(), flow_analyzer=FlowAnalysis()
        )
        runtime = SimulationRuntime(svc, pipeline)
        app.state.services = svc
        app.state.pipeline = pipeline
        app.state.runtime = runtime
        return runtime

    @asynccontextmanager
    async def serverless_lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Everything was wired at import (hosts may skip lifespan events); nothing runs in the
        # background: the simulation advances on live-event polls (routes_events).
        yield

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        engine = None
        svc = services
        if svc is None:
            engine = build_engine(settings.database_url)
            svc = AppServices(
                settings=settings,
                clock=clock or SystemClock(),
                session_factory=build_session_factory(engine),
            )
        svc.bus.bind_loop(asyncio.get_running_loop())
        runtime = wire(app, svc)
        task = asyncio.create_task(runtime.run_forever()) if start_background else None
        try:
            yield
        finally:
            if task is not None:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if engine is not None:
                engine.dispose()

    app = FastAPI(
        title="MedDefender Twin API",
        version="0.1.0",
        summary="Healthcare IoT security simulation with a live digital twin. All data is synthetic.",
        lifespan=serverless_lifespan if settings.serverless else lifespan,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        redoc_url=None,
    )

    @app.middleware("http")
    async def correlation_and_headers(request: Request, call_next: Any) -> Any:
        incoming = request.headers.get("x-correlation-id", "")
        request.state.correlation_id = (
            incoming if _CORRELATION_RE.match(incoming) else str(uuid.uuid4())
        )
        response = await call_next(request)
        response.headers["X-Correlation-ID"] = request.state.correlation_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        if request.url.path.startswith("/api/") and not request.url.path.startswith("/api/docs"):
            response.headers.setdefault("Cache-Control", "no-store")
            response.headers.setdefault(
                "Content-Security-Policy", "default-src 'none'; frame-ancestors 'none'"
            )
        return response

    @app.exception_handler(AppError)
    async def app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error(exc.status_code, exc.code, exc.message, request, exc.details)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        # Never echo submitted values back (they may contain passwords or secrets).
        details = [
            {"loc": list(e.get("loc", ())), "msg": e.get("msg", ""), "type": e.get("type", "")}
            for e in exc.errors()[:20]
        ]
        return _error(422, "VALIDATION_ERROR", "Request validation failed.", request, details)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").capitalize()
        return _error(exc.status_code, code, message, request)

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception) -> JSONResponse:
        logger.exception(
            "Unhandled error (correlation_id=%s)", getattr(request.state, "correlation_id", None)
        )
        return _error(500, "INTERNAL_ERROR", "An unexpected error occurred.", request)

    if settings.serverless:
        svc = services or AppServices(
            settings=settings,
            clock=clock or SystemClock(),
            session_factory=build_session_factory(
                build_engine(settings.database_url, serverless=True)
            ),
        )
        wire(app, svc)

    for module in (
        routes_auth,
        routes_twin,
        routes_telemetry,
        routes_security,
        routes_incidents,
        routes_simulation,
        routes_events,
    ):
        app.include_router(module.router)
    app.include_router(ws.router)
    return app
