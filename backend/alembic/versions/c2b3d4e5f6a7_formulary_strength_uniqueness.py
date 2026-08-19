"""Formulary identity includes strength.

metformin 500 mg and metformin 1000 mg are distinct stock items; the original
(generic_name, form) constraint made them collide on ingestion.

Revision ID: c2b3d4e5f6a7
Revises: b1a2c3d4e5f6
"""
from __future__ import annotations

from alembic import op

revision = "c2b3d4e5f6a7"
down_revision = "b1a2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("formulary_items") as batch:
        batch.drop_constraint("uq_generic_form", type_="unique")
        batch.create_unique_constraint(
            "uq_generic_form_strength", ["generic_name", "form", "strength"]
        )


def downgrade() -> None:
    with op.batch_alter_table("formulary_items") as batch:
        batch.drop_constraint("uq_generic_form_strength", type_="unique")
        batch.create_unique_constraint("uq_generic_form", ["generic_name", "form"])
