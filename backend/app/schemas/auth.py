from __future__ import annotations

import uuid

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole


class LoginRequest(BaseModel):
    email: str
    password: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    role: UserRole
    clinic_id: uuid.UUID | None
    license_no: str | None
    language: str

    model_config = {"from_attributes": True}


class UserCreate(BaseModel):
    email: EmailStr
    full_name: str = Field(min_length=2, max_length=200)
    password: str = Field(min_length=10, max_length=72)
    role: UserRole
    clinic_id: uuid.UUID | None = None
    license_no: str | None = None
    language: str = "uz"
