from __future__ import annotations

import time

import jwt
import pytest

from app.core.config import get_settings
from app.core.security import (
    TokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import UserRole


def test_password_hash_roundtrip():
    hashed = hash_password("correct-horse-battery")
    assert hashed != "correct-horse-battery"
    assert verify_password("correct-horse-battery", hashed)
    assert not verify_password("wrong-horse-battery", hashed)


def test_overlong_password_refused_not_truncated():
    # bcrypt ignores bytes past 72; silently accepting them would mean two
    # different passwords authenticate the same account.
    with pytest.raises(ValueError):
        hash_password("a" * 73)


def test_refresh_token_cannot_be_used_as_access_token():
    token = create_refresh_token("11111111-1111-1111-1111-111111111111")
    with pytest.raises(TokenError):
        decode_token(token, expected_type="access")


def test_token_signed_with_other_key_is_rejected():
    forged = jwt.encode(
        {"sub": "x", "type": "access", "exp": int(time.time()) + 600},
        "not-our-key",
        algorithm="HS256",
    )
    with pytest.raises(TokenError):
        decode_token(forged, expected_type="access")


def test_expired_token_is_rejected(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "access_token_ttl_minutes", -1)
    token = create_access_token(
        "11111111-1111-1111-1111-111111111111", role="doctor", clinic_id=None
    )
    with pytest.raises(TokenError):
        decode_token(token, expected_type="access")


def test_login_and_me(client, clinic_factory, user_factory, auth_headers):
    clinic = clinic_factory()
    user = user_factory(clinic, email="doctor@sihhat.uz")
    headers = auth_headers("doctor@sihhat.uz")
    response = client.get("/api/v1/auth/me", headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert body["email"] == "doctor@sihhat.uz"
    assert body["clinic_id"] == str(user.clinic_id)


def test_login_with_bad_password_is_401(client, clinic_factory, user_factory):
    clinic_factory()
    user_factory(email="doctor2@sihhat.uz")
    response = client.post(
        "/api/v1/auth/login", json={"email": "doctor2@sihhat.uz", "password": "nope-nope-nope"}
    )
    assert response.status_code == 401


def test_unknown_email_and_wrong_password_are_indistinguishable(client, user_factory):
    user_factory(email="known@sihhat.uz")
    a = client.post(
        "/api/v1/auth/login", json={"email": "known@sihhat.uz", "password": "bad-password"}
    )
    b = client.post(
        "/api/v1/auth/login", json={"email": "nobody@sihhat.uz", "password": "bad-password"}
    )
    assert a.status_code == b.status_code == 401
    assert a.json() == b.json()


def test_inactive_user_cannot_log_in(client, user_factory, db):
    user = user_factory(email="gone@sihhat.uz")
    user.is_active = False
    db.flush()
    response = client.post(
        "/api/v1/auth/login", json={"email": "gone@sihhat.uz", "password": "correct-horse-battery"}
    )
    assert response.status_code == 401


def test_missing_token_is_401(client):
    assert client.get("/api/v1/auth/me").status_code == 401


def test_refresh_issues_new_access_token(client, user_factory):
    user_factory(email="refresh@sihhat.uz")
    login = client.post(
        "/api/v1/auth/login",
        json={"email": "refresh@sihhat.uz", "password": "correct-horse-battery"},
    ).json()
    response = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert response.status_code == 200
    assert response.json()["access_token"]


def test_doctor_cannot_create_users(client, clinic_factory, user_factory, auth_headers):
    clinic = clinic_factory()
    user_factory(clinic, email="plaindoc@sihhat.uz", role=UserRole.doctor)
    response = client.post(
        "/api/v1/auth/users",
        headers=auth_headers("plaindoc@sihhat.uz"),
        json={
            "email": "new@sihhat.uz",
            "full_name": "New Nurse",
            "password": "another-long-password",
            "role": "nurse",
        },
    )
    assert response.status_code == 403


def test_admin_cannot_create_superadmin_or_cross_clinic(
    client, clinic_factory, user_factory, auth_headers
):
    clinic_a = clinic_factory(name="A")
    clinic_b = clinic_factory(name="B")
    user_factory(clinic_a, email="admin@sihhat.uz", role=UserRole.admin)
    headers = auth_headers("admin@sihhat.uz")

    escalation = client.post(
        "/api/v1/auth/users",
        headers=headers,
        json={
            "email": "root@sihhat.uz",
            "full_name": "Root",
            "password": "another-long-password",
            "role": "superadmin",
        },
    )
    assert escalation.status_code == 403

    cross = client.post(
        "/api/v1/auth/users",
        headers=headers,
        json={
            "email": "nurse-b@sihhat.uz",
            "full_name": "Nurse B",
            "password": "another-long-password",
            "role": "nurse",
            "clinic_id": str(clinic_b.id),
        },
    )
    assert cross.status_code == 201
    # The requested clinic_id is ignored: an admin can only staff their own clinic.
    assert cross.json()["clinic_id"] == str(clinic_a.id)
