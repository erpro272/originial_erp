"""Seed data. Runs as the database owner.

    python -m seed.run             # seed (fails if already seeded)
    python -m seed.run --if-empty  # dev startup (compose): needs ERP_SEED_DEMO=true, else does nothing.
                                   # Seeds a fresh database, and fills demo data into demo companies
                                   # that have none. Never touches a company that has any data.
    python -m seed.run --reset     # wipe all data, then seed (refused when ERP_ENV=prod)

Logins (password from ERP_SEED_PASSWORD, default ``Demo@12345``):
    owner@demo.example       owner of the demo company
    planner@demo.example     planner        purchaser@demo.example   purchaser
    accountant@demo.example  accountant     owner@second.example     owner of company 2 only
"""

import argparse
import asyncio
import os
import uuid

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core import audit
from app.core.config import get_settings
from app.core.db import set_tenant
from app.core.keys import create_tenant_key
from app.core.models import Membership, Tenant, User
from app.core.permissions import Role
from app.core.security import hash_password
from seed.demo_data import seed_demo, seed_second

PASSWORD = os.environ.get("ERP_SEED_PASSWORD", "Demo@12345")

TENANTS = [
    ("demo", "Demo Manufacturing Co."),
    ("second", "Second Fasteners Pvt Ltd"),
]
USERS = [
    # email, name, [(tenant slug, role)]
    ("owner@demo.example", "Asha Rao", [("demo", Role.OWNER)]),
    ("planner@demo.example", "Vikram Shah", [("demo", Role.PLANNER)]),
    ("purchaser@demo.example", "Neha Kulkarni", [("demo", Role.PURCHASER)]),
    ("accountant@demo.example", "Rahul Mehta", [("demo", Role.ACCOUNTANT)]),
    ("owner@second.example", "Imran Qureshi", [("second", Role.OWNER)]),
]

DEMO_TABLES = ("products", "materials", "customers", "orders", "invoices")

TABLES_IN_DELETE_ORDER = [
    "invoice_transport",
    "invoice_payments",
    "invoice_lines",
    "invoice_parties",
    "extraction_runs",
    "invoice_uploads",
    "invoices",
    "orders",
    "customer_followups",
    "customer_contacts",
    "customer_addresses",
    "customers",
    "product_materials",
    "material_stock",
    "products",
    "materials",
    "tenant_counters",
    "user_preferences",
    "tenant_settings",
    "outbox_events",
    "audit_log",
    "tenant_keys",
    "memberships",
    "users",
    "tenants",
]


async def reset(session: AsyncSession) -> None:
    await session.execute(text(f"TRUNCATE {', '.join(TABLES_IN_DELETE_ORDER)} CASCADE"))


async def seed(session: AsyncSession) -> dict[str, uuid.UUID]:
    pw = hash_password(PASSWORD)
    tenants = {slug: Tenant(id=uuid.uuid4(), slug=slug, name=name) for slug, name in TENANTS}
    session.add_all(tenants.values())
    users = {
        email: User(id=uuid.uuid4(), email=email, full_name=name, password_hash=pw)
        for email, name, _ in USERS
    }
    session.add_all(users.values())
    await session.flush()
    for email, _, roles in USERS:
        for slug, role in roles:
            session.add(Membership(tenant_id=tenants[slug].id, user_id=users[email].id, role=role.value))
    await session.flush()
    for slug, tenant in tenants.items():
        await set_tenant(session, tenant.id)
        await create_tenant_key(session, tenant.id)
        owner = next(e for e, _, rs in USERS if (slug, Role.OWNER) in rs)
        await audit.record(
            session,
            actor_id=users[owner].id,
            action="create",
            entity_type="company",
            entity_id=tenant.id,
            summary=f"Company '{tenant.name}' created (seed)",
        )
    return {slug: t.id for slug, t in tenants.items()}


async def seed_business(session: AsyncSession, ids: dict[str, uuid.UUID]) -> None:
    owner = (await session.execute(select(User.id).where(User.email == "owner@demo.example"))).scalar_one()
    await seed_demo(session, ids["demo"], owner)
    await seed_second(session, ids["second"])


async def has_business_data(session: AsyncSession, tenant_id: uuid.UUID) -> bool:
    """True if the company has any product, material, customer, order or invoice."""
    # Filter by company explicitly: the seed role is a superuser, so RLS does not filter for it.
    for table in DEMO_TABLES:
        query = text(f"SELECT 1 FROM {table} WHERE tenant_id = :t LIMIT 1")  # noqa: S608 - fixed table names
        found = await session.execute(query, {"t": tenant_id})
        if found.first() is not None:
            return True
    return False


async def seed_missing(session: AsyncSession) -> list[str]:
    """Add demo business data to the demo companies that have NONE. Returns the slugs filled.

    Safety: a company with even one product/customer/order/... is left completely alone, and
    only the seeded demo slugs are considered. Runs in the caller's transaction (all or nothing).
    """
    tenants = (
        await session.execute(select(Tenant).where(Tenant.slug.in_([t[0] for t in TENANTS])))
    ).scalars()
    ids = {t.slug: t.id for t in tenants}
    owner = (
        await session.execute(select(User.id).where(User.email == "owner@demo.example"))
    ).scalar_one_or_none()
    filled: list[str] = []
    if owner is None or "demo" not in ids:
        print("seed: demo company or demo owner is missing, not adding demo data")
        return filled
    for slug in ("demo", "second"):
        if slug not in ids:
            continue
        if await has_business_data(session, ids[slug]):
            print(f"seed: company '{slug}' already has data, left untouched")
            continue
        await (seed_demo(session, ids[slug], owner) if slug == "demo" else seed_second(session, ids[slug]))
        filled.append(slug)
    return filled


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--if-empty", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    settings = get_settings()
    if args.reset and settings.is_prod:
        raise SystemExit("Refusing to wipe the database: ERP_ENV=prod.")
    if args.if_empty and not args.reset and not settings.seed_demo:
        print("seed: ERP_SEED_DEMO is not true, no demo data added")
        return
    engine = create_async_engine(settings.database_owner_url)
    async with async_sessionmaker(engine)() as session, session.begin():
        if args.reset:
            await reset(session)
        elif (await session.execute(select(Tenant.id).limit(1))).first() is not None:
            if not args.if_empty:
                raise SystemExit("Already seeded. Use --reset to start over.")
            filled = await seed_missing(session)
            print(f"seed: demo data added to {filled}" if filled else "seed: nothing to add")
            await engine.dispose()
            return
        ids = await seed(session)
        await seed_business(session, ids)
    await engine.dispose()
    print(f"seed: done. Companies: {ids}. Password for all users: {PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
