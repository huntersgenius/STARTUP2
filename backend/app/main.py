"""FastAPI application factory."""

from __future__ import annotations

import logging
import time
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse

from app.api import admin, ai, auth, consultations, health, sync
from app.api import patients as patients_api
from app.core import metrics
from app.core.config import get_settings
from app.core.i18n import resolve_language
from app.core.logging import configure_logging

logger = logging.getLogger("sihhatai.request")

DISCLAIMER_HEADER = "X-Clinical-Disclaimer"
#: HTTP headers are latin-1 only, so the header carries a stable ASCII token
#: and the translated sentence travels in the response body instead.
DISCLAIMER_TOKEN = "not-a-diagnosis; clinician-review-required"


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()

    app = FastAPI(
        title=settings.app_name,
        version="0.1.0",
        description=(
            "Clinical decision support for primary care in Uzbekistan. "
            "Every AI output is a suggestion for a licensed clinician, never a diagnosis."
        ),
        docs_url="/docs",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.environment in ("dev", "test") else [],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def request_context(request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        language = resolve_language(request.headers.get("Accept-Language"))
        request.state.language = language
        started = time.perf_counter()
        try:
            response: Response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            logger.exception(
                "request failed",
                extra={
                    "request_id": request_id,
                    "path": request.url.path,
                    "method": request.method,
                    "duration_ms": round(duration_ms, 2),
                },
            )
            metrics.inc("sihhatai_requests_total", {"path": request.url.path, "status": "500"})
            raise
        duration_ms = (time.perf_counter() - started) * 1000
        response.headers["X-Request-ID"] = request_id
        response.headers["Content-Language"] = language
        # The disclaimer travels on every response, so no client can render a
        # suggestion without having been told what it is.
        response.headers[DISCLAIMER_HEADER] = DISCLAIMER_TOKEN
        logger.info(
            "request",
            extra={
                "request_id": request_id,
                "path": request.url.path,
                "method": request.method,
                "status": response.status_code,
                "duration_ms": round(duration_ms, 2),
                "user_id": getattr(request.state, "user_id", None),
                "clinic_id": getattr(request.state, "clinic_id", None),
            },
        )
        metrics.inc(
            "sihhatai_requests_total",
            {"path": request.url.path, "status": str(response.status_code)},
        )
        metrics.observe(
            "sihhatai_request_duration_seconds",
            duration_ms / 1000,
            {"path": request.url.path},
        )
        return response

    @app.exception_handler(ValueError)
    async def value_error_handler(request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": str(exc)})

    prefix = settings.api_prefix
    app.include_router(health.router)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(patients_api.router, prefix=prefix)
    app.include_router(consultations.router, prefix=prefix)
    app.include_router(ai.router, prefix=prefix)
    app.include_router(sync.router, prefix=prefix)
    app.include_router(admin.router, prefix=prefix)

    if settings.metrics_enabled:

        @app.get("/metrics", include_in_schema=False)
        def prometheus_metrics() -> PlainTextResponse:
            return PlainTextResponse(metrics.render(), media_type="text/plain; version=0.0.4")

    return app


app = create_app()
