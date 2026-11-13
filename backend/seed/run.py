"""Seed data. Runs as the database owner.

    python -m seed.run             # seed (fails if already seeded)
    python -m seed.run --if-empty  # no-op when a tenant already exists (used by compose)
    python -m seed.run --reset     # wipe all data, then seed

Logins (password from ERP_SEED_PASSWORD, default ``Demo@12345``):
    owner@demo.example       owner of BOTH demo companies (shows the company picker)
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

PASSWORD = os.environ.get("ERP_SEED_PASSWORD", "Demo@12345")

TENANTS = [
    ("demo", "Demo Manufacturing Co."),
    ("second", "Second Fasteners Pvt Ltd"),
]
USERS = [
    # email, name, [(tenant slug, role)]
    ("owner@demo.example", "Asha Rao", [("demo", Role.OWNER), ("second", Role.OWNER)]),
    ("planner@demo.example", "Vikram Shah", [("demo", Role.PLANNER)]),
    ("purchaser@demo.example", "Neha Kulkarni", [("demo", Role.PURCHASER)]),
    ("accountant@demo.example", "Rahul Mehta", [("demo", Role.ACCOUNTANT)]),
    ("owner@second.example", "Imran Qureshi", [("second", Role.OWNER)]),
]

TABLES_IN_DELETE_ORDER = [
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


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--if-empty", action="store_true")
    parser.add_argument("--reset", action="store_true")
    args = parser.parse_args()
    engine = create_async_engine(get_settings().database_owner_url)
    async with async_sessionmaker(engine)() as session, session.begin():
        if args.reset:
            await reset(session)
        elif (await session.execute(select(Tenant.id).limit(1))).first() is not None:
            if args.if_empty:
                print("seed: data already present, skipping")
                await engine.dispose()
                return
            raise SystemExit("Already seeded. Use --reset to start over.")
        ids = await seed(session)
    await engine.dispose()
    print(f"seed: done. Companies: {ids}. Password for all users: {PASSWORD}")


if __name__ == "__main__":
    asyncio.run(main())
