"""plan snapshots, cancel / complete

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-16 09:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.core.rls import APP_ROLE, enable_tenant_rls

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("plans", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("plans", sa.Column("cancel_reason", sa.Text(), nullable=True))
    op.create_table(
        "plan_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("plan_id", sa.Uuid(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("inputs", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rule", sa.String(length=16), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("approved_by", sa.Uuid(), nullable=True),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column(
            "tenant_id",
            sa.Uuid(),
            server_default=sa.text("NULLIF(current_setting('app.tenant_id', true), '')::uuid"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["approved_by"], ["users.id"], name=op.f("fk_plan_snapshots_approved_by_users")),
        sa.ForeignKeyConstraint(["plan_id"], ["plans.id"], name=op.f("fk_plan_snapshots_plan_id_plans")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_plan_snapshots")),
        sa.UniqueConstraint("plan_id", "version", name=op.f("uq_plan_snapshots_plan_id_version")),
    )
    op.create_index(op.f("ix_plan_snapshots_plan_id"), "plan_snapshots", ["plan_id"], unique=False)
    op.create_index(op.f("ix_plan_snapshots_tenant_id"), "plan_snapshots", ["tenant_id"], unique=False)
    enable_tenant_rls("plan_snapshots")
    # approved snapshots are never overwritten or deleted by the app
    op.execute(f"REVOKE UPDATE, DELETE ON plan_snapshots FROM {APP_ROLE}")


def downgrade() -> None:
    op.drop_index(op.f("ix_plan_snapshots_tenant_id"), table_name="plan_snapshots")
    op.drop_index(op.f("ix_plan_snapshots_plan_id"), table_name="plan_snapshots")
    op.drop_table("plan_snapshots")
    op.drop_column("plans", "cancel_reason")
    op.drop_column("plans", "cancelled_at")
    op.drop_column("plans", "completed_at")
