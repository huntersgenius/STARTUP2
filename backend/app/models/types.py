"""Dialect-portable column types."""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import JSON, String, Text, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID


class GUID(TypeDecorator):
    """UUID that is native on Postgres and a 36-char string elsewhere."""

    impl = String(36)
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(PGUUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if not isinstance(value, uuid.UUID):
            value = uuid.UUID(str(value))
        return value if dialect.name == "postgresql" else str(value)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value if isinstance(value, uuid.UUID) else uuid.UUID(str(value))


class JSONBType(TypeDecorator):
    """JSONB on Postgres, JSON elsewhere."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class Vector(TypeDecorator):
    """Embedding column.

    Uses pgvector's `vector` type on Postgres when the extension is present,
    and falls back to a JSON-encoded list elsewhere so the identical model
    definition works on SQLite in CI and on edge devices.
    """

    impl = Text
    cache_ok = True

    def __init__(self, dim: int = 1536, **kw: Any) -> None:
        self.dim = dim
        super().__init__(**kw)

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            try:
                from pgvector.sqlalchemy import Vector as PGVector  # type: ignore

                return dialect.type_descriptor(PGVector(self.dim))
            except ImportError:  # pgvector python package absent; store as text
                return dialect.type_descriptor(Text())
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            try:
                import pgvector.sqlalchemy  # noqa: F401

                return list(value)
            except ImportError:
                pass
        return json.dumps([float(x) for x in value])

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, str):
            return json.loads(value)
        return list(value)
