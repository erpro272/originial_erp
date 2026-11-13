"""Test setup: a real PostgreSQL test database (``erp_test``), migrated from scratch.

The API under test connects as ``erp_app`` (RLS applies), exactly like production.
"""

import os

os.environ.setdefault("ERP_ENV", "test")
os.environ.setdefault(
    "ERP_DATABASE_URL", "postgresql+asyncpg://erp_app:erp_app@localhost:5432/erp_test"
)
os.environ.setdefault(
    "ERP_DATABASE_OWNER_URL", "postgresql+asyncpg://erp_owner:erp_owner@localhost:5432/erp_test"
)
os.environ.setdefault("ERP_REDIS_URL", "redis://localhost:6379/15")
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


async def login(
    client: AsyncClient, email: str, tenant_id: uuid.UUID | None = None
) -> dict[str, str]:
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
