"""Layer 1: PostgreSQL row-level security, tested as the real application role."""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError

from app.core.db import Base, get_sessionmaker, global_session, tenant_session
from app.core.models import AuditLog, Membership, Tenant, TenantKey, TenantSetting


async def test_app_role_is_not_privileged(tenants) -> None:
    async with global_session() as s:
        row = (
            await s.execute(text("SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"))
        ).one()
    assert row == (False, False)


async def test_every_tenant_table_has_forced_rls(tenants) -> None:
    tables = [t.name for t in Base.metadata.sorted_tables if "tenant_id" in t.c]
    assert {
        "audit_log",
        "tenant_keys",
        "outbox_events",
        "tenant_settings",
        "user_preferences",
    } <= set(tables)
    async with global_session() as s:
        for name in tables:
            rls, forced = (
                await s.execute(
                    text("SELECT relrowsecurity, relforcerowsecurity FROM pg_class WHERE relname = :n"),
                    {"n": name},
                )
            ).one()
            policies = (
                await s.execute(text("SELECT count(*) FROM pg_policies WHERE tablename = :n"), {"n": name})
            ).scalar_one()
            assert rls and forced and policies >= 1, name


async def test_no_tenant_bound_sees_nothing(tenants) -> None:
    async with global_session() as s:
        for model in (AuditLog, TenantKey, TenantSetting, Membership, Tenant):
            assert (await s.execute(select(model))).first() is None, model.__name__


async def test_tenant_sees_only_its_rows(tenants) -> None:
    a, b = tenants["demo"], tenants["second"]
    async with tenant_session(a) as s:
        s.add(TenantSetting(key="rls-probe", value={"owner": "a"}))
    async with tenant_session(b) as s:
        s.add(TenantSetting(key="rls-probe", value={"owner": "b"}))
    async with tenant_session(a) as s:
        rows = (
            (await s.execute(select(TenantSetting).where(TenantSetting.key == "rls-probe"))).scalars().all()
        )
        assert [r.value for r in rows] == [{"owner": "a"}]
        assert {r.tenant_id for r in (await s.execute(select(AuditLog))).scalars()} == {a}
        assert [t.id for t in (await s.execute(select(Tenant))).scalars()] == [a]
        # Even an explicit filter on the other tenant returns nothing.
        other = await s.execute(select(AuditLog).where(AuditLog.tenant_id == b))
        assert other.first() is None


async def test_cannot_write_into_another_tenant(tenants) -> None:
    with pytest.raises(DBAPIError, match="row-level security"):
        async with tenant_session(tenants["demo"]) as s:
            s.add(TenantSetting(tenant_id=tenants["second"], key="evil", value={}))


async def test_cannot_update_rows_of_another_tenant(tenants) -> None:
    async with tenant_session(tenants["demo"]) as s:
        res = await s.execute(
            text("UPDATE tenant_settings SET value = '{}' WHERE tenant_id = :b"),
            {"b": tenants["second"]},
        )
        assert res.rowcount == 0  # type: ignore[attr-defined]


async def test_audit_log_is_append_only_for_app(tenants) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with tenant_session(tenants["demo"]) as s:
            await s.execute(text("DELETE FROM audit_log"))
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with tenant_session(tenants["demo"]) as s:
            await s.execute(text("UPDATE audit_log SET summary = 'x'"))


async def test_tenant_keys_cannot_be_modified_by_app(tenants) -> None:
    with pytest.raises(ProgrammingError, match="permission denied"):
        async with tenant_session(tenants["demo"]) as s:
            await s.execute(text("UPDATE tenant_keys SET is_active = false"))


async def test_setting_is_transaction_local(tenants) -> None:
    """A pooled connection must not leak the previous request's tenant."""
    async with tenant_session(tenants["demo"]):
        pass
    async with get_sessionmaker()() as s, s.begin():
        val = (await s.execute(text("SELECT current_setting('app.tenant_id', true)"))).scalar()
        assert not val
