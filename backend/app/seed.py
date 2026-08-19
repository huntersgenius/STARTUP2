"""Seed a development installation: one clinic, one of each role.

Idempotent — `python -m app.seed --if-empty` is safe to run on every boot.
Refuses to run outside dev/test so demo credentials can never reach a pilot.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.db import get_sessionmaker
from app.core.security import hash_password
from app.models import Clinic, ClinicType, Patient, Sex, User, UserRole

DEMO_PASSWORD = "sihhat-demo-password"


def seed(if_empty: bool = False) -> int:
    settings = get_settings()
    if settings.environment not in ("dev", "test"):
        print(
            f"refusing to seed demo accounts in environment={settings.environment}", file=sys.stderr
        )
        return 1

    session = get_sessionmaker()()
    try:
        existing = session.execute(select(func.count()).select_from(Clinic)).scalar_one()
        if existing and if_empty:
            print("database already seeded; nothing to do")
            return 0

        clinic = Clinic(
            name="Chinoz tumani 4-sonli QVP",
            region="Toshkent viloyati",
            type=ClinicType.gov,
            tier=1,
            offline_mode=True,
        )
        session.add(clinic)
        session.flush()

        people = [
            ("doctor@sihhat.uz", "Dilshod Karimov", UserRole.doctor, "UZ-D-10231"),
            ("feldsher@sihhat.uz", "Nodira Ergasheva", UserRole.feldsher, "UZ-F-55120"),
            ("nurse@sihhat.uz", "Gulnora Tosheva", UserRole.nurse, None),
            ("admin@sihhat.uz", "Sardor Aliyev", UserRole.admin, None),
        ]
        for email, name, role, license_no in people:
            session.add(
                User(
                    email=email,
                    full_name=name,
                    hashed_password=hash_password(DEMO_PASSWORD),
                    role=role,
                    clinic_id=clinic.id,
                    license_no=license_no,
                )
            )
        session.add(
            User(
                email="root@sihhat.uz",
                full_name="Platform Superadmin",
                hashed_password=hash_password(DEMO_PASSWORD),
                role=UserRole.superadmin,
                clinic_id=None,
            )
        )

        patient = Patient(
            clinic_id=clinic.id, mrn="P-DEMO0001", dob=date(1979, 3, 8), sex=Sex.female
        )
        session.add(patient)
        session.flush()
        patient.set_pii(
            {
                "full_name": "Zulfiya Ismoilova",
                "phone": "+998901112233",
                "address": "Chinoz tumani, Navro'z MFY",
            }
        )
        session.commit()
        print(
            f"seeded clinic {clinic.name!r} with {len(people) + 1} users; password: {DEMO_PASSWORD}"
        )
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Seed development data")
    parser.add_argument("--if-empty", action="store_true", help="no-op when data already exists")
    args = parser.parse_args()
    raise SystemExit(seed(if_empty=args.if_empty))
