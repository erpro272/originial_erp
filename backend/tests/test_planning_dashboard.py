"""Plans dashboard: list by stage, open any plan, frozen approved snapshots, cancel, automatic completion."""

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.db import set_tenant
from tests.conftest import AsyncClient
from tests.test_planning_demo import _demo


async def _approve(client: AsyncClient, h: dict[str, str], pid: str, note: str = "ok") -> dict:  # type: ignore[type-arg]
    await client.post(f"/planning/plans/{pid}/generate", headers=h)
    r = await client.post(
        f"/planning/plans/{pid}/approve", json={"note": note, "raise_open_pos": True}, headers=h
    )
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_dashboard_snapshots_and_reapproval(client: AsyncClient) -> None:
    h = await _demo(client, "dash-snap")
    plan = (await client.get("/planning/plan", headers=h)).json()
    pid = plan["id"]
    rows = (await client.get("/planning/plans", headers=h)).json()
    assert [(r["number"], r["stage"], r["orders"]) for r in rows] == [("PLAN-001", "draft", 4)]

    approved = await _approve(client, h, pid)
    assert approved["snapshots"][0]["version"] == 1
    [row] = (await client.get("/planning/plans", headers=h)).json()
    assert row["stage"] == "approved" and row["snapshot_version"] == 1 and row["approved_at"]
    money = (row["value"], row["contribution"], row["margin"])
    assert row["value"] > 0

    # opening it shows the frozen approved version
    snap = (await client.get(f"/planning/plans/{pid}", headers=h)).json()
    assert snap["view"] == "snapshot" and snap["snapshot"]["version"] == 1
    approved_contribution = snap["result"]["finance"]["with"]["contribution"]

    # a day passing doesn't need re-approval: re-reading the plan keeps it approved
    assert not (await client.get(f"/planning/plans/{pid}?view=live", headers=h)).json()["needs_reapproval"]

    # data changes after approval (company overheads up): the live view moves, the snapshot doesn't
    rules = (await client.get("/planning/rules", headers=h)).json()
    await client.put("/planning/rules", json={**rules, "overhead_pct": rules["overhead_pct"] + 5}, headers=h)
    live = (await client.get(f"/planning/plans/{pid}?view=live", headers=h)).json()
    assert live["view"] == "live" and live["needs_reapproval"]
    assert live["result"]["finance"]["with"]["contribution"] < approved_contribution
    snap = (await client.get(f"/planning/plans/{pid}", headers=h)).json()
    assert (
        snap["view"] == "snapshot"
        and snap["result"]["finance"]["with"]["contribution"] == approved_contribution
    )
    [row] = (await client.get("/planning/plans", headers=h)).json()
    assert row["stage"] == "needs_reapproval" and (row["value"], row["contribution"], row["margin"]) == money

    # re-approve: v2 is added, v1 stays
    r = await client.post(f"/planning/plans/{pid}/approve", json={"note": "overheads up", "raise_open_pos": True},
                          headers=h)  # fmt: skip
    assert r.status_code == 200, r.text
    assert [s["version"] for s in r.json()["snapshots"]] == [2, 1]
    [row] = (await client.get("/planning/plans", headers=h)).json()
    assert row["stage"] == "approved" and row["snapshot_version"] == 2 and row["contribution"] < money[1]


async def test_app_cannot_change_or_delete_an_approved_snapshot(client: AsyncClient) -> None:
    h = await _demo(client, "dash-ro")
    pid = (await client.get("/planning/plan", headers=h)).json()["id"]
    await _approve(client, h, pid)
    tenant = (await client.get("/auth/me", headers=h)).json()["company"]["id"]
    eng_ = create_async_engine(get_settings().database_url)  # the app's own role (erp_app)
    for sql in ("UPDATE plan_snapshots SET note = 'changed'", "DELETE FROM plan_snapshots"):
        async with async_sessionmaker(eng_)() as s, s.begin():
            await set_tenant(s, tenant)
            with pytest.raises(DBAPIError, match="permission denied"):
                await s.execute(text(sql))
    await eng_.dispose()


async def test_cancel_a_draft_frees_its_orders_and_approved_cannot_be_cancelled(client: AsyncClient) -> None:
    h = await _demo(client, "dash-cancel")
    plan = (await client.get("/planning/plan", headers=h)).json()
    pid, picked = plan["id"], plan["result"]["selection"]["selected"]
    assert (
        await client.post(f"/planning/plans/{pid}/cancel", json={"reason": ""}, headers=h)
    ).status_code == 422
    out = (await client.post(f"/planning/plans/{pid}/cancel", json={"reason": "Customer moved dates"},
                             headers=h)).json()  # fmt: skip
    assert out["status"] == "cancelled" and out["cancel_reason"] == "Customer moved dates"
    for oid in picked:  # back to accepted, not in planning
        o = (await client.get(f"/orders/{oid}", headers=h)).json()
        assert o["status"] == "accepted" and not o["marked_for_planning"]
    [row] = (await client.get("/planning/plans", headers=h)).json()
    assert row["stage"] == "cancelled"
    # a cancelled plan is history: edits refused, and it isn't the current plan any more
    assert (
        await client.patch(f"/planning/plans/{pid}", json={"rule": "deadline"}, headers=h)
    ).status_code == 400
    assert (await client.get("/planning/plan", headers=h)).json() is None

    # + New plan, approve it, then try to cancel the approved one
    new = (await client.post("/planning/plans", headers=h)).json()
    assert new["number"] == "PLAN-002"
    await client.patch(f"/planning/plans/{new['id']}", json={"selected": picked}, headers=h)
    await _approve(client, h, new["id"])
    bad = await client.post(f"/planning/plans/{new['id']}/cancel", json={"reason": "x"}, headers=h)
    assert bad.status_code == 400
    stages = {r["number"]: r["stage"] for r in (await client.get("/planning/plans", headers=h)).json()}
    assert stages == {"PLAN-001": "cancelled", "PLAN-002": "approved"}


async def test_plan_completes_when_all_its_orders_are_shipped(client: AsyncClient) -> None:
    h = await _demo(client, "dash-done")
    plan = (await client.get("/planning/plan", headers=h)).json()
    pid, picked = plan["id"], plan["result"]["selection"]["selected"]
    await _approve(client, h, pid)
    for i, oid in enumerate(picked):
        for status in ("in_production", "completed", "shipped"):
            if i == len(picked) - 1 and status == "shipped":
                break  # the last one is completed, not shipped yet
            r = await client.patch(f"/orders/{oid}", json={"status": status}, headers=h)
            assert r.status_code == 200, r.text
    [row] = (await client.get("/planning/plans", headers=h)).json()
    # one order is made ("completed") but not shipped yet; production progress doesn't need re-approval
    assert row["stage"] == "approved"
    await client.patch(f"/orders/{picked[-1]}", json={"status": "shipped"}, headers=h)
    [row] = (await client.get("/planning/plans", headers=h)).json()
    assert row["stage"] == "completed" and row["completed_at"]
    out = (await client.get(f"/planning/plans/{pid}", headers=h)).json()
    assert out["status"] == "completed" and out["view"] == "snapshot"
    hist = (await client.get(f"/planning/plans/{pid}/history", headers=h)).json()
    assert hist[0]["kind"] == "completed"
