"""Engine/session wiring.

The same models must run on Postgres (production) and SQLite (CI, edge
devices, and the Flutter test harness's fake server). Dialect-specific types
are isolated in `app/models/types.py` rather than sprinkled through models.
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

_engine: Engine | None = None
_SessionLocal: sessionmaker[Session] | None = None


def _connect_args(url: str) -> dict:
    if url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(
            settings.database_url,
            connect_args=_connect_args(settings.database_url),
            pool_pre_ping=True,
            future=True,
        )
        if settings.database_url.startswith("sqlite"):

            @event.listens_for(_engine, "connect")
            def _fk_on(dbapi_conn, _record):  # pragma: no cover - trivial
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()

    return _engine


def get_sessionmaker() -> sessionmaker[Session]:
    global _SessionLocal
    if _SessionLocal is None:
        _SessionLocal = sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)
    return _SessionLocal


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request, always closed."""
    session = get_sessionmaker()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Test helper: drop cached engine/sessionmaker after settings change."""
    global _engine, _SessionLocal
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionLocal = None
