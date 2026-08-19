"""Enforce append-only audit_logs in the database, not just in the app.

The audit chain is the regulatory sandbox evidence. Application discipline is
not enough: a trigger makes UPDATE and DELETE fail even for a direct psql
session, so tampering requires visibly dropping the trigger.

Revision ID: b1a2c3d4e5f6
Revises: a980669ea994
"""
from __future__ import annotations

from alembic import op

revision = "b1a2c3d4e5f6"
down_revision = "a980669ea994"
branch_labels = None
depends_on = None

TRIGGER_FN = """
CREATE OR REPLACE FUNCTION sihhat_audit_append_only() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs is append-only (attempted %)', TG_OP;
END;
$$ LANGUAGE plpgsql;
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        # SQLite (CI, edge devices) relies on the application-level chain
        # verification in app/core/audit.py instead.
        return
    op.execute(TRIGGER_FN)
    op.execute(
        """
        CREATE TRIGGER audit_logs_no_update
        BEFORE UPDATE OR DELETE ON audit_logs
        FOR EACH ROW EXECUTE FUNCTION sihhat_audit_append_only();
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_update ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS sihhat_audit_append_only()")
