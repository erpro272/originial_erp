import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.ai.service import AIError, MockAIClient, get_ai_client
from app.core import events
from app.core.db import tenant_session
from app.core.models import OutboxEvent


async def test_outbox_dispatch_per_tenant(tenants) -> None:
    seen: list[tuple[str, str]] = []

    @events.subscribe("test.ok")
    async def ok(session, event) -> None:  # type: ignore[no-untyped-def]
        seen.append((str(event.tenant_id), event.payload["n"]))

    @events.subscribe("test.fail")
    async def fail(session, event) -> None:  # type: ignore[no-untyped-def]
        raise RuntimeError("handler broke")

    async with tenant_session(tenants["demo"]) as s:
        await events.emit(s, "test.ok", {"n": "a"})
        await events.emit(s, "test.fail", {"n": "x"})
    async with tenant_session(tenants["second"]) as s:
        await events.emit(s, "test.ok", {"n": "b"})

    await events.dispatch_outbox()
    assert sorted(seen) == sorted([(str(tenants["demo"]), "a"), (str(tenants["second"]), "b")])

    async with tenant_session(tenants["demo"]) as s:
        failed = (await s.execute(select(OutboxEvent).where(OutboxEvent.type == "test.fail"))).scalar_one()
        assert failed.processed_at is None and failed.attempts == 1
        assert "handler broke" in (failed.last_error or "")
    await events.dispatch_outbox()  # processed events are not delivered twice
    assert len(seen) == 2


async def test_ai_mock_mode_without_key() -> None:
    client = get_ai_client()
    assert client.mode == "mock"
    res = await client.extract_json(task="echo", system="", instructions="", schema={}, files=[])
    assert res.ok and res.data == {"message": "mock mode is working"}


async def test_ai_mock_missing_fixture() -> None:
    with pytest.raises(AIError):
        await MockAIClient().extract_json(task="nope", system="", instructions="", schema={}, files=[])


async def test_health(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.json() == {
        "status": "ok",
        "database": True,
        "redis": True,
        "storage": True,
        "ai_mode": "mock",
    }
