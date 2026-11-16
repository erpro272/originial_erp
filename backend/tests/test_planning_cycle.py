"""One active plan at a time; approved plans are history; re-approval is a revision of the same plan."""

import asyncio
from datetime import timedelta
from decimal import Decimal

from httpx import AsyncClient

from tests import factories as fx
from tests.conftest import TODAY, Company, headers_for, make_company
from tests.test_planning import _order, _setup_factory


async def _co(
    client: AsyncClient, slug: str, stock: str = "1"
) -> tuple[Company, dict[str, str], dict[str, str]]:
    co = await make_company(slug)
    h = await headers_for(client, co)
    bolts = await fx.product(
        co.id, "B1", "Hex bolts", price=1000, cost=800, bom=[("STL", "Steel", Decimal("0.001"))]
    )
    nuts = await fx.product(co.id, "N1", "Nuts", price=500, cost=400)
    await fx.stock(co.id, "STL", Decimal(stock))
    d = {"bolts": str(bolts), "nuts": str(nuts), "cust": str(await fx.customer(co.id, "Acme Ltd"))}
    await _setup_factory(client, h, d)
    return co, h, d


async def _set_stock(tid, code: str, on_hand: str) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import select, update

    from app.catalog.models import Material, MaterialStock
    from app.core.db import tenant_session

    async with tenant_session(tid) as s:
        m = (await s.execute(select(Material).where(Material.code == code))).scalar_one()
        await s.execute(
            update(MaterialStock).where(MaterialStock.material_id == m.id).values(on_hand=Decimal(on_hand))
        )


async def _send(client: AsyncClient, h: dict[str, str], *ids: str) -> dict:  # type: ignore[type-arg]
    r = await client.post(
        "/orders/planning-selection", headers=h, json={"order_ids": list(ids), "marked": True}
    )
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def _plans(client: AsyncClient, h: dict[str, str]) -> list[dict]:  # type: ignore[type-arg]
    return (await client.get("/planning/plans", headers=h)).json()  # type: ignore[no-any-return]


async def _approve(client: AsyncClient, h: dict[str, str], pid: str) -> dict:  # type: ignore[type-arg]
    await client.post(f"/planning/plans/{pid}/generate", headers=h)
    r = await client.post(f"/planning/plans/{pid}/approve", headers=h, json={"raise_open_pos": True})
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_send_to_planning_fills_the_one_active_plan(client: AsyncClient) -> None:
    _, h, d = await _co(client, "cyc-send")
    assert (await client.get("/planning/plan", headers=h)).json() is None  # nothing sent: no plan
    a = await _order(client, h, d["bolts"], d["cust"], "500", 10, mark=False)
    b = await _order(client, h, d["nuts"], d["cust"], "500", 12, mark=False)
    first = await _send(client, h, a)
    assert first["created"] and first["plan"]["stage"] == "draft"
    second = await _send(client, h, b)  # goes into the same plan
    assert not second["created"] and second["plan"]["id"] == first["plan"]["id"]
    plan = (await client.get("/planning/plan", headers=h)).json()
    assert plan["id"] == first["plan"]["id"] and set(plan["result"]["selection"]["selected"]) == {a, b}
    # "+ New plan" can't start a second one
    r = await client.post("/planning/plans", headers=h)
    assert r.status_code == 400 and plan["number"] in r.json()["error"]["message"]
    # Orders shows which plan each order is in
    o = (await client.get(f"/orders/{a}", headers=h)).json()
    assert o["plan"] == {"id": plan["id"], "number": plan["number"], "stage": "draft"}
    assert len(await _plans(client, h)) == 1


async def test_sending_at_the_same_moment_still_makes_one_plan(client: AsyncClient) -> None:
    _, h, d = await _co(client, "cyc-race")
    ids = [await _order(client, h, d["bolts"], d["cust"], "100", 10 + i, mark=False) for i in range(3)]
    res = await asyncio.gather(*[
        client.post("/orders/planning-selection", headers=h, json={"order_ids": [i], "marked": True}) for i in ids
    ])  # fmt: skip
    assert all(r.status_code == 200 for r in res), [r.text for r in res]
    assert len({r.json()["plan"]["id"] for r in res}) == 1
    plans = await _plans(client, h)
    assert len(plans) == 1 and plans[0]["orders"] == 3


async def test_orders_added_after_generate_send_the_plan_back_to_draft(client: AsyncClient) -> None:
    _, h, d = await _co(client, "cyc-regen")
    a = await _order(client, h, d["bolts"], d["cust"], "500", 10)
    plan = (await client.get("/planning/plan", headers=h)).json()
    await client.post(f"/planning/plans/{plan['id']}/generate", headers=h)
    b = await _order(client, h, d["nuts"], d["cust"], "500", 12)  # sent while awaiting approval
    now = (await client.get("/planning/plan", headers=h)).json()
    nb = now["result"]["selection"]["orders"][b]["number"]
    assert now["id"] == plan["id"] and now["status"] == "draft" and now["regenerate"]["added"] == [nb]
    r = await client.post(f"/planning/plans/{plan['id']}/approve", headers=h, json={})
    assert r.status_code == 400 and "Generate" in r.json()["error"]["message"]
    # removing it again: the plan is as generated, awaiting approval again
    await client.post("/orders/planning-selection", headers=h, json={"order_ids": [b], "marked": False})
    back = (await client.get("/planning/plan", headers=h)).json()
    assert back["status"] == "generated" and back["regenerate"] is None
    await _send(client, h, b)
    gen = (await client.post(f"/planning/plans/{plan['id']}/generate", headers=h)).json()
    assert gen["status"] == "generated" and gen["regenerate"] is None
    assert set(gen["result"]["selection"]["selected"]) == {a, b}


async def test_after_approval_no_active_plan_and_no_double_booking(client: AsyncClient) -> None:
    _, h, d = await _co(client, "cyc-after")
    a = await _order(client, h, d["bolts"], d["cust"], "500", 10)
    pid = (await client.get("/planning/plan", headers=h)).json()["id"]
    ap = await _approve(client, h, pid)
    assert ap["status"] == "approved"
    assert (await client.get("/planning/plan", headers=h)).json() is None  # no plan started by itself
    assert len(await _plans(client, h)) == 1
    # its order is planned: it can't be sent to another plan
    r = await client.post("/orders/planning-selection", headers=h, json={"order_ids": [a], "marked": True})
    assert r.status_code == 400
    # even if someone moves it back to accepted, it stays in the approved plan
    assert (await client.patch(f"/orders/{a}", headers=h, json={"status": "accepted"})).status_code == 200
    r = await client.post("/orders/planning-selection", headers=h, json={"order_ids": [a], "marked": True})
    assert r.status_code == 400 and f"is already in {ap['number']}" in r.json()["error"]["message"]
    r = await client.patch(f"/orders/{a}", headers=h, json={"marked_for_planning": True})
    assert r.status_code == 400
    # the owner starts the next cycle explicitly
    nxt = await client.post("/planning/plans", headers=h)
    assert nxt.status_code == 201 and nxt.json()["number"] != ap["number"]
    assert a not in nxt.json()["result"]["selection"]["orders"]  # never a candidate of the next plan


async def test_reapproval_only_for_significant_changes_and_says_why(client: AsyncClient) -> None:
    co, h, d = await _co(client, "cyc-rev", stock="1")
    await _order(client, h, d["bolts"], d["cust"], "500", 20)  # needs 0.5 t, 1 t in stock
    pid = (await client.get("/planning/plan", headers=h)).json()["id"]
    await _approve(client, h, pid)

    async def live() -> dict:  # type: ignore[type-arg]
        return (await client.get(f"/planning/plans/{pid}?view=live", headers=h)).json()  # type: ignore[no-any-return]

    # good news (more stock) is logged, not a re-approval
    await _set_stock(co.id, "STL", "3")
    p = await live()
    assert not p["needs_reapproval"] and p["revision"]["causes"] == ["STL stock 1 → 3 t"]
    # a small cost rise stays under the 5% limit
    rules = (await client.get("/planning/rules", headers=h)).json()
    await client.put("/planning/rules", headers=h, json=rules | {"overhead_pct": 7.5})
    p = await live()
    money = next(c for c in p["revision"]["changes"] if c["kind"] == "money")
    assert not p["needs_reapproval"] and not money["significant"]
    # stock taken away: the material is now short -> revision 2, with the reason
    await _set_stock(co.id, "STL", "0.1")
    p = await live()
    assert p["needs_reapproval"] and p["revision"]["number"] == 2
    short = next(c for c in p["revision"]["changes"] if c["kind"] == "material_short")
    assert short["significant"] and "Steel" in short["title"] and "STL stock 1 → 0.1 t" in short["why"]
    plans = await _plans(client, h)
    assert len(plans) == 1 and plans[0]["stage"] == "needs_reapproval" and plans[0]["revision"] == 2
    # stock back: the approved version holds again
    await _set_stock(co.id, "STL", "1")
    assert not (await live())["needs_reapproval"]


async def test_downtime_makes_an_order_later_and_re_approval_is_the_same_plan(client: AsyncClient) -> None:
    _, h, d = await _co(client, "cyc-down")
    await _order(client, h, d["nuts"], d["cust"], "1000", 4)  # CNC, 2 days, tight
    pid = (await client.get("/planning/plan", headers=h)).json()["id"]
    ap = await _approve(client, h, pid)
    row = ap["result"]["sequence"]["rows"][0]
    f = (await client.get("/planning/factory", headers=h)).json()
    f["downtime"] = [{"machine": "CNC", "day": row["start"], "reason": "Breakdown"}]
    assert (await client.put("/planning/factory", headers=h, json=f)).status_code == 200
    p = (await client.get(f"/planning/plans/{pid}?view=live", headers=h)).json()
    later = next(c for c in p["revision"]["changes"] if c["kind"] in ("order_later", "order_late"))
    assert (
        p["needs_reapproval"]
        and later["significant"]
        and any("CNC downtime added" in w for w in later["why"])
    )
    # re-approve: same plan, version 2 kept next to version 1, still no active plan
    again = (
        await client.post(f"/planning/plans/{pid}/approve", headers=h, json={"note": "Accept the delay"})
    ).json()
    assert (
        again["id"] == pid
        and not again["needs_reapproval"]
        and [s["version"] for s in again["snapshots"]] == [2, 1]
    )
    assert (await client.get("/planning/plan", headers=h)).json() is None and len(
        await _plans(client, h)
    ) == 1


async def test_a_later_plan_does_not_disturb_an_earlier_approved_one(client: AsyncClient) -> None:
    _, h, d = await _co(client, "cyc-two")
    await _order(client, h, d["bolts"], d["cust"], "1000", 6)
    p1 = (await client.get("/planning/plan", headers=h)).json()["id"]
    await _approve(client, h, p1)
    await _order(client, h, d["bolts"], d["cust"], "1000", 6)  # same machine, same week: starts PLAN-002
    p2 = (await client.get("/planning/plan", headers=h)).json()
    assert p2["id"] != p1
    await _approve(client, h, p2["id"])
    first = (await client.get(f"/planning/plans/{p1}?view=live", headers=h)).json()
    assert not first["needs_reapproval"]  # PLAN-002 was planned around PLAN-001, not the other way round
    stages = {p["id"]: p["stage"] for p in await _plans(client, h)}
    assert stages == {p1: "approved", p2["id"]: "approved"}
    assert TODAY + timedelta(days=1) > TODAY  # dates are relative to the test clock
