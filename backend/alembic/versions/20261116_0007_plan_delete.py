"""plans: deleted_at / deleted_by (owner removes a never-approved plan, a trace is kept)

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-16 12:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plans", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("plans", sa.Column("deleted_by", sa.Uuid(), nullable=True))
    op.create_foreign_key(op.f("fk_plans_deleted_by_users"), "plans", "users", ["deleted_by"], ["id"])


def downgrade() -> None:
    op.drop_constraint(op.f("fk_plans_deleted_by_users"), "plans", type_="foreignkey")
    op.drop_column("plans", "deleted_by")
    op.drop_column("plans", "deleted_at")
