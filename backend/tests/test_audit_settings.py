import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core import audit
from app.core.db import tenant_session
from app.core.models import AuditLog
from tests.conftest import login


async def test_login_is_audited(client: AsyncClient, owner) -> None:
    r = await client.get("/audit-log", headers=owner, params={"action": "login"})
    assert r.status_code == 200
    entry = r.json()["items"][0]
    assert entry["actor_name"] == "Asha Rao" and entry["entity_type"] == "user"
    assert entry["request_id"]


@pytest.mark.parametrize(
    "who", ["planner@demo.example", "purchaser@demo.example", "accountant@demo.example"]
)
async def test_only_owner_reads_audit_log(client: AsyncClient, who: str) -> None:
    h = await login(client, who)
    assert (await client.get("/audit-log", headers=h)).status_code == 403


async def test_setting_write_audited_with_before_after(client: AsyncClient, owner) -> None:
    key = "order-ranking"
    assert (await client.get(f"/settings/{key}", headers=owner)).status_code == 404
    r1 = await client.put(
        f"/settings/{key}", headers=owner, json={"value": {"weights": {"profit": 1}}}
    )
    assert r1.status_code == 200
    await client.put(f"/settings/{key}", headers=owner, json={"value": {"weights": {"profit": 2}}})
    assert (await client.get(f"/settings/{key}", headers=owner)).json()["value"] == {
        "weights": {"profit": 2}
    }
    log = (
        await client.get(
            "/audit-log", headers=owner, params={"entity_type": "setting", "entity_id": key}
        )
    ).json()
    assert [e["action"] for e in log["items"]] == ["update", "create"]
    assert log["items"][0]["before"] == {"weights": {"profit": 1}}
    assert log["items"][0]["after"] == {"weights": {"profit": 2}}


async def test_non_owner_cannot_write_settings(client: AsyncClient, planner) -> None:
    r = await client.put("/settings/order-ranking", headers=planner, json={"value": {}})
    assert r.status_code == 403
    assert (await client.get("/settings/order-ranking", headers=planner)).status_code in (200, 404)


async def test_invalid_setting_key(client: AsyncClient, owner) -> None:
    r = await client.put("/settings/Bad Key!", headers=owner, json={"value": {}})
    assert r.status_code == 400


async def test_audit_rolls_back_with_the_change(tenants) -> None:
    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        async with tenant_session(tenants["demo"]) as s:
            await audit.record(
                s, actor_id=None, action="create", entity_type="probe", entity_id="rb"
            )
            raise Boom
    async with tenant_session(tenants["demo"]) as s:
        assert (
            await s.execute(select(AuditLog).where(AuditLog.entity_type == "probe"))
        ).first() is None


async def test_audit_redacts_sensitive_fields(tenants) -> None:
    async with tenant_session(tenants["demo"]) as s:
        e = await audit.record(
            s,
            actor_id=None,
            action="update",
            entity_type="customer",
            entity_id="c1",
            before={"pan": "AAACT2727Q", "name": "A"},
            after={"pan": "AAACT2727R", "name": "B"},
        )
        assert e.before == {"pan": "[redacted]", "name": "A"}
        assert e.after == {"pan": "[redacted]", "name": "B"}


def test_audit_diff() -> None:
    assert audit.diff({"a": 1, "b": 2}, {"a": 1, "b": 3, "c": 4}) == (
        {"b": 2, "c": None},
        {"b": 3, "c": 4},
    )


async def test_preferences_are_per_user(client: AsyncClient, owner, planner) -> None:
    key = "table.orders.columns"
    await client.put(f"/me/preferences/{key}", headers=owner, json={"value": {"visible": ["id"]}})
    assert (await client.get(f"/me/preferences/{key}", headers=owner)).json()["value"] == {
        "visible": ["id"]
    }
    assert (await client.get(f"/me/preferences/{key}", headers=planner)).json()["value"] == {}
