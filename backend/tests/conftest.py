from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from datetime import date

# Settings are read at import time by several modules, so the test environment
# has to be in place before `app` is imported anywhere.
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+pysqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/15")
os.environ.setdefault("METRICS_ENABLED", "true")

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.orm import Session, sessionmaker  # noqa: E402
from sqlalchemy.pool import StaticPool  # noqa: E402

from app.core.db import get_db  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Base, Clinic, ClinicType, Patient, User, UserRole  # noqa: E402


@pytest.fixture()
def engine():
    eng = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(eng)
    try:
        yield eng
    finally:
        eng.dispose()


@pytest.fixture()
def db(engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.rollback()
        session.close()


@pytest.fixture()
def app(engine, db):
    application = create_app()

    def _override_db() -> Iterator[Session]:
        # Hand the request the same session the test holds, so assertions see
        # the rows the endpoint wrote without a second connection.
        yield db
        db.flush()

    application.dependency_overrides[get_db] = _override_db
    return application


@pytest.fixture()
def client(app) -> Iterator[TestClient]:
    with TestClient(app) as c:
        yield c


# --- factories -----------------------------------------------------------


@pytest.fixture()
def clinic_factory(db):
    def _make(name: str = "Chinoz QVP", region: str = "Tashkent", **kw) -> Clinic:
        clinic = Clinic(
            name=name,
            region=region,
            type=kw.pop("type", ClinicType.gov),
            tier=kw.pop("tier", 1),
            offline_mode=kw.pop("offline_mode", True),
            **kw,
        )
        db.add(clinic)
        db.flush()
        return clinic

    return _make


@pytest.fixture()
def user_factory(db):
    def _make(
        clinic: Clinic | None = None,
        role: UserRole = UserRole.doctor,
        password: str = "correct-horse-battery",
        email: str | None = None,
        **kw,
    ) -> User:
        user = User(
            email=email or f"{uuid.uuid4().hex[:10]}@sihhat.uz",
            full_name=kw.pop("full_name", "Dilshod Karimov"),
            hashed_password=hash_password(password),
            role=role,
            clinic_id=clinic.id if clinic else None,
            license_no=kw.pop("license_no", "UZ-12345"),
            **kw,
        )
        db.add(user)
        db.flush()
        return user

    return _make


@pytest.fixture()
def patient_factory(db):
    def _make(clinic: Clinic, name: str = "Aziza Yusupova", **kw) -> Patient:
        patient = Patient(
            id=uuid.uuid4(),
            clinic_id=clinic.id,
            mrn=kw.pop("mrn", f"P-{uuid.uuid4().hex[:8].upper()}"),
            dob=kw.pop("dob", date(1985, 4, 12)),
            sex=kw.pop("sex", "female"),
            chronic_flags=kw.pop("chronic_flags", []),
            pii_blob=b"",
        )
        patient.set_pii({"full_name": name, "phone": "+998901234567", **kw.pop("pii", {})})
        db.add(patient)
        db.flush()
        return patient

    return _make


@pytest.fixture()
def auth_headers(client):
    def _make(email: str, password: str = "correct-horse-battery") -> dict[str, str]:
        response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
        assert response.status_code == 200, response.text
        return {"Authorization": f"Bearer {response.json()['access_token']}"}

    return _make
