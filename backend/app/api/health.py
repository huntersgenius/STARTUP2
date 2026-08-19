from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import text

from app.api.deps import DbSession
from app.core.config import get_settings

router = APIRouter(tags=["ops"])


def _redis_status() -> str:
    settings = get_settings()
    try:
        import redis  # imported lazily so the API boots without redis installed

        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=1)
        client.ping()
        return "ok"
    except Exception as exc:  # noqa: BLE001 - health must never raise
        return f"unavailable: {type(exc).__name__}"


@router.get("/health")
def health(db: DbSession) -> dict:
    settings = get_settings()
    try:
        db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception as exc:  # noqa: BLE001
        db_status = f"unavailable: {type(exc).__name__}"

    checks = {"database": db_status, "redis": _redis_status()}
    healthy = all(v == "ok" for v in checks.values())
    return {
        "status": "ok" if healthy else "degraded",
        "app": settings.app_name,
        "environment": settings.environment,
        "build_sha": settings.build_sha,
        "checks": checks,
    }


@router.get("/health/live")
def liveness() -> dict:
    """Process liveness only — never touches a dependency."""
    return {"status": "ok", "build_sha": get_settings().build_sha}
