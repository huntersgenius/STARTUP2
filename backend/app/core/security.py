"""Password hashing and JWT issuance/verification."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_pwd = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)

TokenType = Literal["access", "refresh"]


class TokenError(Exception):
    """Raised for any token that is missing, expired, or of the wrong type."""


def hash_password(raw: str) -> str:
    # bcrypt silently truncates at 72 bytes; refuse rather than accept a
    # password whose tail is ignored.
    if len(raw.encode("utf-8")) > 72:
        raise ValueError("password must be at most 72 bytes")
    return _pwd.hash(raw)


def verify_password(raw: str, hashed: str) -> bool:
    try:
        return _pwd.verify(raw, hashed)
    except ValueError:
        return False


def _create_token(
    subject: str, token_type: TokenType, ttl: timedelta, extra: dict[str, Any] | None = None
) -> str:
    settings = get_settings()
    now = datetime.now(UTC)
    payload: dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "iat": int(now.timestamp()),
        "exp": int((now + ttl).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.secret_key, algorithm=settings.jwt_algorithm)


def create_access_token(user_id: str, *, role: str, clinic_id: str | None) -> str:
    settings = get_settings()
    return _create_token(
        user_id,
        "access",
        timedelta(minutes=settings.access_token_ttl_minutes),
        {"role": role, "clinic_id": clinic_id},
    )


def create_refresh_token(user_id: str) -> str:
    settings = get_settings()
    return _create_token(user_id, "refresh", timedelta(days=settings.refresh_token_ttl_days))


def decode_token(token: str, *, expected_type: TokenType) -> dict[str, Any]:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
    if payload.get("type") != expected_type:
        # A refresh token must never be usable as an access token.
        raise TokenError(f"expected {expected_type} token, got {payload.get('type')!r}")
    return payload
