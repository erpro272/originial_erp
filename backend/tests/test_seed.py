"""Startup seeding must fill in a half-seeded database without ever touching real data."""

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.catalog.models import Material
from app.core.config import get_settings
from seed import run as seed_run


async def test_fills_empty_demo_companies_then_leaves_them_alone(tenants) -> None:  # type: ignore[no-untyped-def]
    """Old volume case: companies and users exist (Step 0 seed) but no business data."""
    eng = create_async_engine(get_settings().database_owner_url)
    async with async_sessionmaker(eng)() as s:
        assert not await seed_run.has_business_data(s, tenants["demo"])
        assert await seed_run.seed_missing(s) == ["demo", "second"]
        await seed_run.set_tenant(s, tenants["demo"])
        assert (await s.execute(text("SELECT count(*) FROM customers"))).scalar_one() > 0
        assert (await s.execute(text("SELECT count(*) FROM orders"))).scalar_one() > 0
        # second run in the same transaction: everything has data now, nothing is touched
        assert await seed_run.seed_missing(s) == []
        await s.rollback()  # leave the shared test database as it was
    await eng.dispose()


async def test_company_with_any_data_is_never_seeded(tenants) -> None:  # type: ignore[no-untyped-def]
    eng = create_async_engine(get_settings().database_owner_url)
    async with async_sessionmaker(eng)() as s:
        await seed_run.set_tenant(s, tenants["demo"])
        s.add(Material(code="X1", name="Real material", unit="t"))
        await s.flush()
        assert await seed_run.seed_missing(s) == ["second"]  # demo has data (one material): skipped
        await seed_run.set_tenant(s, tenants["demo"])
        assert (
            await s.execute(
                text("SELECT count(*) FROM customers WHERE tenant_id = :t"), {"t": tenants["demo"]}
            )
        ).scalar_one() == 0
        await s.rollback()
    await eng.dispose()
