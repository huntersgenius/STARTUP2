"""Shared FastAPI dependencies: identity, language, and clinic row scoping."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Annotated

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.i18n import resolve_language, translate
from app.core.security import TokenError, decode_token
from app.models.user import User, UserRole

bearer_scheme = HTTPBearer(auto_error=False)

DbSession = Annotated[Session, Depends(get_db)]


def get_language(
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> str:
    return resolve_language(accept_language)


Language = Annotated[str, Depends(get_language)]


def get_current_user(
    request: Request,
    db: DbSession,
    language: Language,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
) -> User:
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=translate("error.unauthorized", language),
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(credentials.credentials, expected_type="access")
    except TokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    user = db.get(User, uuid.UUID(payload["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=translate("error.unauthorized", language),
        )
    # Stash for the audit middleware; it must never guess the actor.
    request.state.user_id = str(user.id)
    request.state.clinic_id = str(user.clinic_id) if user.clinic_id else None
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: UserRole):
    """Dependency factory guarding an endpoint by role."""
    allowed = set(roles)

    def _guard(user: CurrentUser, language: Language) -> User:
        if user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=translate("error.forbidden", language),
            )
        return user

    return _guard


def assert_clinic_scope(user: User, clinic_id: uuid.UUID | None, language: str = "uz") -> None:
    """The single chokepoint for cross-clinic access.

    Superadmins are the only role that may read across clinics, and even they
    leave an audit row behind (written by the caller). Everyone else is pinned
    to their own clinic — a 404, not a 403, so the existence of another
    clinic's record is not leaked.
    """
    if user.role is UserRole.superadmin:
        return
    if user.clinic_id is None or clinic_id is None or user.clinic_id != clinic_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=translate("error.not_found", language),
        )


def scoped_clinic_ids(user: User) -> Iterable[uuid.UUID] | None:
    """None means 'all clinics' (superadmin); otherwise the user's own clinic."""
    if user.role is UserRole.superadmin:
        return None
    return [user.clinic_id] if user.clinic_id else []
