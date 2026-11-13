"""Foundations: identity, tenant keys, audit log, outbox, settings, preferences + RLS.

Revision ID: 0001
Revises:
Create Date: 2026-11-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql as pg

from app.core.rls import APP_ROLE, enable_tenant_rls, grant_app

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_DEFAULT = sa.text("NULLIF(current_setting('app.tenant_id', true), '')::uuid")
NOW = sa.text("now()")
CURRENT_TENANT = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"
CURRENT_USER = "NULLIF(current_setting('app.user_id', true), '')::uuid"


def _ts() -> list[sa.Column]:
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    ]


def _tenant_col() -> sa.Column:
    return sa.Column("tenant_id", sa.Uuid(), server_default=TENANT_DEFAULT, nullable=False)


def upgrade() -> None:
    # ---- global identity tables -------------------------------------------------------
    op.create_table(
        "tenants",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(64), nullable=False, unique=True),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        *_ts(),
    )
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
        *_ts(),
    )
    op.create_table(
        "memberships",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tenant_id", sa.Uuid(), sa.ForeignKey("tenants.id"), nullable=False, index=True),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_id_user_id"),
        sa.CheckConstraint(
            "role IN ('owner','planner','purchaser','accountant')", name="ck_memberships_role"
        ),
    )

    # ---- tenant-scoped tables ----------------------------------------------------------
    op.create_table(
        "tenant_keys",
        sa.Column("id", sa.Uuid(), primary_key=True),
        _tenant_col(),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("wrapped_key", sa.LargeBinary(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
    )
    op.create_index("ix_tenant_keys_tenant_id", "tenant_keys", ["tenant_id"])
    op.create_index(
        "uq_tenant_keys_one_active",
        "tenant_keys",
        ["tenant_id"],
        unique=True,
        postgresql_where=sa.text("is_active"),
    )

    op.create_table(
        "audit_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        _tenant_col(),
        sa.Column("at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("actor_id", sa.Uuid()),
        sa.Column("actor_name", sa.String(200)),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(64)),
        sa.Column("summary", sa.Text()),
        sa.Column("before", pg.JSONB()),
        sa.Column("after", pg.JSONB()),
        sa.Column("request_id", sa.String(64)),
    )
    op.create_index("ix_audit_log_tenant_id", "audit_log", ["tenant_id"])
    op.create_index("ix_audit_log_at", "audit_log", ["at"])
    op.create_index("ix_audit_log_actor_id", "audit_log", ["actor_id"])
    op.create_index("ix_audit_log_entity", "audit_log", ["entity_type", "entity_id"])

    op.create_table(
        "outbox_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
        _tenant_col(),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("payload", pg.JSONB(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=NOW, nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True)),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text()),
    )
    op.create_index("ix_outbox_events_tenant_id", "outbox_events", ["tenant_id"])
    op.create_index("ix_outbox_events_type", "outbox_events", ["type"])
    op.create_index(
        "ix_outbox_events_pending",
        "outbox_events",
        ["tenant_id", "id"],
        postgresql_where=sa.text("processed_at IS NULL"),
    )

    op.create_table(
        "tenant_settings",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant_col(),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", pg.JSONB(), nullable=False),
        *_ts(),
        sa.UniqueConstraint("tenant_id", "key", name="uq_tenant_settings_tenant_id_key"),
    )
    op.create_table(
        "user_preferences",
        sa.Column("id", sa.Uuid(), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        _tenant_col(),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id"), nullable=False, index=True),
        sa.Column("key", sa.String(100), nullable=False),
        sa.Column("value", pg.JSONB(), nullable=False),
        *_ts(),
        sa.UniqueConstraint(
            "tenant_id", "user_id", "key", name="uq_user_preferences_tenant_id_user_id_key"
        ),
    )

    # ---- Layer 1: row-level security ---------------------------------------------------
    for table in ("tenant_keys", "outbox_events", "tenant_settings", "user_preferences"):
        enable_tenant_rls(table)
    enable_tenant_rls("audit_log")
    # Audit log is append-only for the application.
    op.execute(f"REVOKE UPDATE, DELETE ON audit_log FROM {APP_ROLE}")
    op.execute(f"REVOKE UPDATE, DELETE, INSERT ON tenant_keys FROM {APP_ROLE}")
    op.execute(f"GRANT INSERT ON tenant_keys TO {APP_ROLE}")

    # Memberships: visible to the bound tenant, or to the bound user (needed at login).
    op.execute("ALTER TABLE memberships ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE memberships FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY membership_visibility ON memberships FOR SELECT "
        f"USING (tenant_id = {CURRENT_TENANT} OR user_id = {CURRENT_USER})"
    )
    op.execute(
        "CREATE POLICY membership_write ON memberships FOR ALL "
        f"USING (tenant_id = {CURRENT_TENANT}) WITH CHECK (tenant_id = {CURRENT_TENANT})"
    )
    grant_app("memberships")

    # Tenants: a user sees only the companies they belong to.
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE tenants FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_visibility ON tenants FOR SELECT USING ("
        f"id = {CURRENT_TENANT} OR EXISTS (SELECT 1 FROM memberships m "
        f"WHERE m.tenant_id = tenants.id AND m.user_id = {CURRENT_USER}))"
    )
    grant_app("tenants", "SELECT")

    # Users: global identity (no tenant column). Not RLS-scoped; never exposed in bulk.
    grant_app("users", "SELECT, UPDATE")

    # System jobs (outbox worker) list tenant ids without seeing any tenant data.
    op.execute(
        """
        CREATE FUNCTION erp_active_tenant_ids() RETURNS SETOF uuid
        LANGUAGE sql STABLE SECURITY DEFINER SET search_path = public AS
        $$ SELECT id FROM tenants WHERE is_active $$
        """
    )
    op.execute("REVOKE ALL ON FUNCTION erp_active_tenant_ids() FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION erp_active_tenant_ids() TO {APP_ROLE}")
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE}")


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS erp_active_tenant_ids()")
    for t in (
        "user_preferences",
        "tenant_settings",
        "outbox_events",
        "audit_log",
        "tenant_keys",
        "memberships",
        "users",
        "tenants",
    ):
        op.drop_table(t)
