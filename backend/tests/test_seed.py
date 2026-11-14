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


async def test_old_demo_database_gets_the_current_planning_demo_once(tenants) -> None:  # type: ignore[no-untyped-def]
    """git pull on a machine whose demo DB predates the planning demo: startup upgrades it one time."""
    from seed import planning_demo

    eng = create_async_engine(get_settings().database_owner_url)
    t = tenants["demo"]
    q = {"t": t}
    async with async_sessionmaker(eng)() as s:
        assert await seed_run.seed_missing(s) == ["demo", "second"]
        # make it look like an old database: no routes, no BOMs, no version marker, other ticks
        await s.execute(text("DELETE FROM route_steps WHERE tenant_id = :t"), q)
        await s.execute(text("DELETE FROM product_materials WHERE tenant_id = :t"), q)
        await s.execute(
            text("DELETE FROM tenant_settings WHERE tenant_id = :t AND key = 'seed.planning-demo'"), q
        )
        await s.execute(text("UPDATE orders SET marked_for_planning = (number = 'ORD-1036') "
                             "WHERE tenant_id = :t AND status = 'accepted'"), q)  # fmt: skip
        assert await seed_run.seed_missing(s) == []  # no new company filled...
        routes = (
            await s.execute(text("SELECT count(*) FROM route_steps WHERE tenant_id = :t"), q)
        ).scalar_one()
        assert routes > 0  # ...but the planning demo was re-applied
        ticked = "SELECT number FROM orders WHERE tenant_id = :t AND marked_for_planning ORDER BY 1"
        assert list((await s.execute(text(ticked), q)).scalars()) == [
            n for n, (marked, _) in sorted(planning_demo.CANDIDATES.items()) if marked
        ]
        # once on the current version, the owner's own changes are kept on every later start
        await s.execute(text("UPDATE orders SET marked_for_planning = false WHERE tenant_id = :t"), q)
        assert not await planning_demo.upgrade_if_old(s, t)
        assert list((await s.execute(text(ticked), q)).scalars()) == []
        # a company without the demo orders is never touched
        assert not await planning_demo.upgrade_if_old(s, tenants["second"])
        await s.rollback()
    await eng.dispose()


async def test_old_two_company_demo_login_is_fixed(tenants) -> None:  # type: ignore[no-untyped-def]
    """Old DBs: owner@demo.example was in both companies -> stuck on "Choose a company" without a picker."""
    from app.core.models import Membership, User

    eng = create_async_engine(get_settings().database_owner_url)
    async with async_sessionmaker(eng)() as s:
        owner = (
            await s.execute(text("SELECT id FROM users WHERE email = 'owner@demo.example'"))
        ).scalar_one()
        s.add(Membership(tenant_id=tenants["second"], user_id=owner, role="owner"))
        real = User(email="real@second.example", full_name="Real", password_hash="x")
        s.add(real)
        await s.flush()
        s.add(Membership(tenant_id=tenants["demo"], user_id=real.id, role="owner"))
        s.add(Membership(tenant_id=tenants["second"], user_id=real.id, role="owner"))
        await s.flush()
        assert await seed_run.drop_stale_demo_memberships(s) == 1
        q = "SELECT count(*) FROM memberships WHERE user_id = :u"
        assert (await s.execute(text(q), {"u": owner})).scalar_one() == 1
        assert (await s.execute(text(q), {"u": real.id})).scalar_one() == 2  # a real user is never touched
        assert await seed_run.drop_stale_demo_memberships(s) == 0
        await s.rollback()
    await eng.dispose()
