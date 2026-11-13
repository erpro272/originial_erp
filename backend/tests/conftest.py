"""Test setup: a real PostgreSQL test database (``erp_test``), migrated from scratch.

The API under test connects as ``erp_app`` (RLS applies), exactly like production.
"""

import os

os.environ.setdefault("ERP_ENV", "test")
os.environ.setdefault("ERP_DATABASE_URL", "postgresql+asyncpg://erp_app:erp_app@localhost:5432/erp_test")
os.environ.setdefault(
    "ERP_DATABASE_OWNER_URL", "postgresql+asyncpg://erp_owner:erp_owner@localhost:5432/erp_test"
)
os.environ.setdefault("ERP_REDIS_URL", "redis://localhost:6379/15")
os.environ["ERP_JOBS_INLINE"] = "true"
os.environ.pop("ANTHROPIC_API_KEY", None)  # tests always run the AI in mock mode

import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from alembic import command
from app.core.config import get_settings
from app.core.redis import get_redis
from app.main import create_app
from seed import run as seed_run

PASSWORD = seed_run.PASSWORD
BACKEND = Path(__file__).resolve().parents[1]


def _migrate_fresh() -> None:
    owner_url = get_settings().database_owner_url
    import asyncio

    async def drop() -> None:
        eng = create_async_engine(owner_url)
        async with eng.begin() as c:
            await c.execute(text("DROP SCHEMA public CASCADE"))
            await c.execute(text("CREATE SCHEMA public"))
            await c.execute(text("GRANT USAGE ON SCHEMA public TO erp_app"))
        await eng.dispose()

    asyncio.run(drop())
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    cfg.attributes["url"] = owner_url
    command.upgrade(cfg, "head")


def pytest_sessionstart(session: pytest.Session) -> None:
    _migrate_fresh()


@pytest.fixture(scope="session")
async def tenants() -> dict[str, uuid.UUID]:
    """Seed once per session (as the owner role). Returns {slug: tenant_id}."""
    eng = create_async_engine(get_settings().database_owner_url)
    async with async_sessionmaker(eng)() as s, s.begin():
        await seed_run.reset(s)
        ids = await seed_run.seed(s)
    await eng.dispose()
    return ids


@pytest.fixture(autouse=True)
async def _clean_redis() -> AsyncIterator[None]:
    await get_redis().flushdb()
    yield


@pytest.fixture(scope="session")
def app():  # type: ignore[no-untyped-def]
    return create_app()


@pytest.fixture
async def client(app, tenants) -> AsyncIterator[AsyncClient]:  # type: ignore[no-untyped-def]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test/api") as c:
        yield c


async def login(client: AsyncClient, email: str, tenant_id: uuid.UUID | None = None) -> dict[str, str]:
    body: dict[str, str] = {"email": email, "password": PASSWORD}
    if tenant_id:
        body["tenant_id"] = str(tenant_id)
    r = await client.post("/auth/login", json=body)
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


@pytest.fixture
async def owner(client, tenants) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return await login(client, "owner@demo.example", tenants["demo"])


@pytest.fixture
async def planner(client) -> dict[str, str]:  # type: ignore[no-untyped-def]
    return await login(client, "planner@demo.example")


# ---- per-module fresh company (isolated data for feature tests) ------------------------

from datetime import date  # noqa: E402

from app.core import clock  # noqa: E402
from app.core.db import set_tenant  # noqa: E402
from app.core.keys import create_tenant_key  # noqa: E402
from app.core.models import Membership, Tenant, User  # noqa: E402
from app.core.security import hash_password  # noqa: E402

TODAY = date(2026, 11, 13)  # a Friday


@pytest.fixture(autouse=True)
def _pin_today():  # type: ignore[no-untyped-def]
    clock.set_today(TODAY)
    yield
    clock.set_today(None)


class Company:
    def __init__(self, tenant_id: uuid.UUID, emails: dict[str, str]) -> None:
        self.id = tenant_id
        self.emails = emails  # role -> email


async def make_company(slug: str) -> Company:
    """New tenant with one user per role (password PASSWORD) and its encryption key."""
    eng = create_async_engine(get_settings().database_owner_url)
    tid = uuid.uuid4()
    emails = {
        r: f"{r}.{slug}.{tid.hex[:6]}@test.example" for r in ("owner", "planner", "purchaser", "accountant")
    }
    async with async_sessionmaker(eng)() as s, s.begin():
        s.add(Tenant(id=tid, slug=f"{slug}-{tid.hex[:8]}", name=f"{slug.title()} Co"))
        pw = hash_password(PASSWORD)
        for role, email in emails.items():
            u = User(id=uuid.uuid4(), email=email, full_name=f"{role.title()} {slug}", password_hash=pw)
            s.add(u)
            await s.flush()
            s.add(Membership(tenant_id=tid, user_id=u.id, role=role))
        await s.flush()
        await set_tenant(s, tid)
        await create_tenant_key(s, tid)
    await eng.dispose()
    return Company(tid, emails)


async def headers_for(client: AsyncClient, company: Company, role: str = "owner") -> dict[str, str]:
    return await login(client, company.emails[role])
