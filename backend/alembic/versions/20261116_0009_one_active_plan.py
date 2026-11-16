"""one active plan per company

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-16
"""

from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Older data may hold more than one draft: keep the newest per company, cancel the rest (kept in history).
    op.execute("""
        UPDATE plans p SET status = 'cancelled', cancelled_at = now(),
               cancel_reason = 'Only one active plan is allowed; a newer draft was kept'
        WHERE p.status IN ('draft', 'generated') AND p.deleted_at IS NULL
          AND EXISTS (SELECT 1 FROM plans q WHERE q.tenant_id = p.tenant_id AND q.status IN ('draft', 'generated')
                      AND q.deleted_at IS NULL AND q.created_at > p.created_at)
    """)
    op.create_index(
        "uq_plans_one_active", "plans", ["tenant_id"], unique=True,
        postgresql_where="status IN ('draft', 'generated') AND deleted_at IS NULL",
    )  # fmt: skip


def downgrade() -> None:
    op.drop_index("uq_plans_one_active", table_name="plans")
