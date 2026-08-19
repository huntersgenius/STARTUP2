from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, Language, require_roles
from app.core import audit
from app.core.config import get_settings
from app.core.i18n import translate
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import User, UserRole
from app.schemas.auth import LoginRequest, RefreshRequest, TokenPair, UserCreate, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _issue(user: User) -> TokenPair:
    settings = get_settings()
    return TokenPair(
        access_token=create_access_token(
            str(user.id),
            role=user.role.value,
            clinic_id=str(user.clinic_id) if user.clinic_id else None,
        ),
        refresh_token=create_refresh_token(str(user.id)),
        expires_in=settings.access_token_ttl_minutes * 60,
    )


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, db: DbSession, language: Language) -> TokenPair:
    user = db.execute(
        select(User).where(User.email == payload.email.lower().strip())
    ).scalar_one_or_none()
    # Same failure for unknown user and wrong password: no account enumeration.
    if (
        user is None
        or not user.is_active
        or not verify_password(payload.password, user.hashed_password)
    ):
        audit.record(
            db,
            action="auth.login_failed",
            entity_type="user",
            entity_id=str(user.id) if user else None,
            metadata={"reason": "invalid_credentials"},
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=translate("error.unauthorized", language),
        )
    audit.record(
        db,
        action="auth.login",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=user.id,
        clinic_id=user.clinic_id,
        metadata={"role": user.role.value},
    )
    return _issue(user)


@router.post("/refresh", response_model=TokenPair)
def refresh(payload: RefreshRequest, db: DbSession, language: Language) -> TokenPair:
    try:
        claims = decode_token(payload.refresh_token, expected_type="refresh")
    except TokenError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    user = db.get(User, uuid.UUID(claims["sub"]))
    if user is None or not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=translate("error.unauthorized", language),
        )
    return _issue(user)


@router.get("/me", response_model=UserOut)
def me(user: CurrentUser) -> User:
    return user


@router.post(
    "/users",
    response_model=UserOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_roles(UserRole.admin, UserRole.superadmin))],
)
def create_user(payload: UserCreate, db: DbSession, actor: CurrentUser, language: Language) -> User:
    # A clinic admin may only create users inside their own clinic; only a
    # superadmin may place a user in an arbitrary clinic or create superadmins.
    clinic_id = payload.clinic_id
    if actor.role is UserRole.admin:
        if payload.role in (UserRole.superadmin,):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=translate("error.forbidden", language),
            )
        clinic_id = actor.clinic_id

    email = payload.email.lower().strip()
    if db.execute(select(User).where(User.email == email)).scalar_one_or_none():
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="email already registered")

    user = User(
        email=email,
        full_name=payload.full_name,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        clinic_id=clinic_id,
        license_no=payload.license_no,
        language=payload.language,
    )
    db.add(user)
    db.flush()
    audit.record(
        db,
        action="user.created",
        entity_type="user",
        entity_id=user.id,
        actor_user_id=actor.id,
        clinic_id=clinic_id,
        metadata={"role": user.role.value},
    )
    return user
