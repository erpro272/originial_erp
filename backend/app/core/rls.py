"""Helpers used by Alembic migrations to put a table under row-level security."""

from alembic import op

APP_ROLE = "erp_app"


def enable_tenant_rls(table: str) -> None:
    """Enable + FORCE RLS so even the table owner is filtered, and grant the app role."""
    op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
    op.execute(
        f'CREATE POLICY tenant_isolation ON "{table}" '
        "USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid) "
        "WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)"
    )
    grant_app(table)


def grant_app(table: str, privileges: str = "SELECT, INSERT, UPDATE, DELETE") -> None:
    op.execute(f'GRANT {privileges} ON "{table}" TO {APP_ROLE}')
