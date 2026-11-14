"""Planning API: one connected plan, from selection to approval, and how other modules move it."""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from tests import factories as fx
from tests.conftest import TODAY, Company, headers_for, make_company


@pytest.fixture(scope="module")
async def co() -> Company:
    return await make_company("plan")


@pytest.fixture(scope="module")
async def data(co: Company) -> dict[str, str]:
    bolts = await fx.product(
        co.id, "B1", "Hex bolts", price=1000, cost=800, bom=[("STL", "Steel", Decimal("0.001"))]
    )
    nuts = await fx.product(co.id, "N1", "Nuts", price=500, cost=400)
    await fx.stock(co.id, "STL", Decimal("1"))  # 1 t: enough for 1,000 bolts
    cust = await fx.customer(co.id, "Acme Ltd")
    return {"bolts": str(bolts), "nuts": str(nuts), "cust": str(cust)}


async def _setup_factory(client: AsyncClient, h: dict[str, str], d: dict[str, str]) -> None:
    f = (await client.get("/planning/factory", headers=h)).json()
    f["departments"] = [{"name": "Shop", "hours_per_day": "100", "cost_per_hour_paise": 20_000}]
    f["machines"] = [
        {"name": "Press", "department": "Shop", "hours_per_shift": "8", "shifts_per_day": 1, "operators": 1,
         "cost_per_hour_paise": 50_000, "night_shift_cost_per_hour_paise": 30_000},
        {"name": "CNC", "department": "Shop", "hours_per_shift": "8", "shifts_per_day": 1, "operators": 1,
         "cost_per_hour_paise": 60_000, "night_shift_cost_per_hour_paise": 30_000},
    ]  # fmt: skip
    for r in f["routes"]:
        r["steps"] = [{"machine": "Press" if r["product"] == "Hex bolts" else "CNC", "setup_hours": "0",
                       "minutes_per_unit": "0.96"}]  # 1,000 pcs = 16 h = 2 days  # fmt: skip
    for m in f["materials"]:
        m |= {"price_per_unit_paise": 30_000_00, "express_cost_paise": 5_000_00, "express_days": 2}
    r = await client.put("/planning/factory", headers=h, json=f)
    assert r.status_code == 200, r.text
    assert [m["name"] for m in r.json()["machines"]] == ["Press", "CNC"]


async def _order(client: AsyncClient, h: dict[str, str], product: str, cust: str, qty: str, ship_in: int,
                 mark: bool = True) -> str:  # fmt: skip
    body = {"customer_id": cust, "product_id": product, "quantity": qty, "unit_price_paise": 100_00,
            "ship_date": str(TODAY + timedelta(days=ship_in)), "status": "accepted"}  # fmt: skip
    r = await client.post("/orders", headers=h, json=body)
    assert r.status_code == 201, r.text
    oid: str = r.json()["id"]
    if mark:
        await client.post("/orders/planning-selection", headers=h, json={"order_ids": [oid], "marked": True})
    return oid


async def test_full_flow(client: AsyncClient, co: Company, data: dict[str, str]) -> None:
    h = await headers_for(client, co)
    await _setup_factory(client, h, data)
    assert (await client.get("/planning/plan", headers=h)).json() is None

    a = await _order(client, h, data["bolts"], data["cust"], "1000", 10)
    b = await _order(client, h, data["bolts"], data["cust"], "1500", 3)  # b + a need 2.5 t: 1.5 t short
    c = await _order(client, h, data["nuts"], data["cust"], "500", 12, mark=False)  # candidate, not ticked

    r = await client.post("/planning/plans", headers=h)
    assert r.status_code == 201, r.text
    plan = r.json()
    pid, res = plan["id"], plan["result"]
    assert plan["number"] == "PLAN-001" and plan["status"] == "draft"
    assert set(res["selection"]["selected"]) == {a, b}  # orders sent to Planning are ticked
    assert c in res["selection"]["orders"]
    # Deadline rule: b (ships in 3 days) first.
    assert [x["id"] for x in res["sequence"]["rows"]] == [b, a]
    assert any(n["code"] == "STL" and n["qty"] == 1.5 for n in res["purchase_needs"])
    # Only one working plan at a time.
    assert (await client.post("/planning/plans", headers=h)).status_code == 400

    # Preview a reorder: nothing is saved, and the diff says what changes.
    pv = await client.patch(f"/planning/plans/{pid}?preview=true", headers=h, json={"sequence": [a, b]})
    assert pv.status_code == 200, pv.text
    assert pv.json()["diff"]["deliveries"]  # b would now ship later
    again = (await client.get("/planning/plan", headers=h)).json()
    assert again["version"] == plan["version"] and again["result"]["sequence"]["rows"][0]["id"] == b

    # Ticking another order changes every tab, and the history says so.
    up = (await client.patch(f"/planning/plans/{pid}", headers=h, json={"selected": [a, b, c]})).json()
    assert set(up["tabs"]) >= {1, 2, 3, 4, 5}
    assert up["plan"]["last_change"]["summary"].startswith("Orders selected · added ORD-")

    # Lock b: it keeps its slot, so moving it is refused.
    await client.patch(f"/planning/plans/{pid}", headers=h, json={"lock": {b: True}})
    seq = [
        x["id"] for x in (await client.get("/planning/plan", headers=h)).json()["result"]["sequence"]["rows"]
    ]
    moved = [x for x in seq if x != b] + [b]
    assert (
        await client.patch(f"/planning/plans/{pid}", headers=h, json={"sequence": moved})
    ).status_code == 400

    # Generate, raise the PO now, and approve.
    gen = (await client.post(f"/planning/plans/{pid}/generate", headers=h)).json()
    assert gen["status"] == "generated"
    stl = next(n for n in gen["result"]["purchase_needs"] if n["code"] == "STL")
    r = await client.post(f"/planning/plans/{pid}/approve", headers=h, json={})
    assert r.status_code == 400 and "not raised" in r.json()["error"]["message"]
    po = (
        await client.post(
            f"/planning/plans/{pid}/purchase-requests", headers=h, json={"material_id": stl["material"]}
        )
    ).json()
    assert next(n for n in po["result"]["purchase_needs"] if n["code"] == "STL")["requested"]
    reqs = (await client.get("/planning/purchase-requests", headers=h)).json()
    assert (
        reqs[0]["material"] == "Steel"
        and reqs[0]["source"] == "raise_now"
        and reqs[0]["status"] == "requested"
    )

    ap = (await client.post(f"/planning/plans/{pid}/approve", headers=h, json={"note": "Go"})).json()
    assert ap["status"] == "approved" and not ap["needs_reapproval"]
    finish = {x["id"]: x["finish"] for x in ap["result"]["sequence"]["rows"]}
    o = (await client.get(f"/orders/{a}", headers=h)).json()
    assert o["status"] == "planned" and o["promised_date"] == finish[a]

    # A change in Orders moves the approved plan back to "needs re-approval".
    r = await client.patch(f"/orders/{a}", headers=h, json={"quantity": "1200"})
    assert r.status_code == 200, r.text
    after = (await client.get("/planning/plan", headers=h)).json()
    assert after["needs_reapproval"] and after["last_change"]["summary"].startswith("Plan updated")
    hist = (await client.get(f"/planning/plans/{pid}/history", headers=h)).json()
    assert {"approved", "generated", "po", "refresh"} <= {x["kind"] for x in hist}

    # Another company never sees this plan.
    other = await make_company("plan-other")
    assert (await client.get("/planning/plan", headers=await headers_for(client, other))).json() is None


async def test_penalty_rule_and_permissions(client: AsyncClient) -> None:
    co = await make_company("plan2")
    h = await headers_for(client, co)
    rules = (await client.get("/planning/rules", headers=h)).json()
    assert rules["penalty_mode"] == "fixed"
    r = await client.put(
        "/planning/rules", headers=h, json=rules | {"penalty_mode": "percent", "penalty_percent": 1}
    )
    assert r.json()["penalty_mode"] == "percent"
    planner = await headers_for(client, co, "planner")
    purchaser = await headers_for(client, co, "purchaser")
    assert (await client.put("/planning/rules", headers=planner, json=rules)).status_code == 403
    assert (await client.post("/planning/plans", headers=purchaser)).status_code == 403
    p = (await client.post("/planning/plans", headers=planner)).json()
    assert (
        await client.post(f"/planning/plans/{p['id']}/approve", headers=planner, json={})
    ).status_code == 403


async def test_factory_validation(client: AsyncClient) -> None:
    co = await make_company("plan3")
    h = await headers_for(client, co)
    f = (await client.get("/planning/factory", headers=h)).json()
    bad = f | {"departments": [{"name": "A", "hours_per_day": "8", "cost_per_hour_paise": 1}],
               "machines": [{"name": "M", "department": "Nope", "hours_per_shift": "8", "shifts_per_day": 1,
                             "operators": 1, "cost_per_hour_paise": 1, "night_shift_cost_per_hour_paise": 1}]}  # fmt: skip
    r = await client.put("/planning/factory", headers=h, json=bad)
    assert r.status_code == 400 and "doesn't exist" in r.json()["error"]["message"]
    closed = f | {"downtime": [{"machine": None, "day": str(date(2026, 12, 25)), "reason": "Christmas"}]}
    assert (await client.put("/planning/factory", headers=h, json=closed)).json()["downtime"][0][
        "reason"
    ] == "Christmas"


async def test_ticks_and_orders_stay_in_sync_both_ways(client: AsyncClient) -> None:
    """Ticked in Planning == "In planning" in Orders, and orders sent later always show up."""
    co = await make_company("plan-sync")
    h = await headers_for(client, co)
    bolts = await fx.product(co.id, "B1", "Bolts")
    cust = str(await fx.customer(co.id, "Sync Ltd"))
    a = await _order(client, h, str(bolts), cust, "100", 10)
    b = await _order(client, h, str(bolts), cust, "100", 12)
    c = await _order(client, h, str(bolts), cust, "100", 14, mark=False)

    plan = (
        await client.get("/planning/plan", headers=h)
    ).json()  # orders were sent: a draft starts by itself
    assert plan["status"] == "draft" and set(plan["result"]["selection"]["selected"]) == {a, b}
    pid = plan["id"]

    async def marked(oid: str) -> bool:
        return bool((await client.get(f"/orders/{oid}", headers=h)).json()["marked_for_planning"])

    # Untick b in Planning -> no longer "In planning" in Orders; tick c -> it is.
    await client.patch(f"/planning/plans/{pid}", headers=h, json={"selected": [a, c]})
    assert not await marked(b) and await marked(c)
    # Send b again from Orders -> it is ticked again (even though it was unticked before).
    await client.post("/orders/planning-selection", headers=h, json={"order_ids": [b], "marked": True})
    sel = (await client.get("/planning/plan", headers=h)).json()["result"]["selection"]
    assert set(sel["selected"]) == {a, b, c}
    # Remove from Planning in Orders -> unticked here.
    await client.post("/orders/planning-selection", headers=h, json={"order_ids": [c], "marked": False})
    sel = (await client.get("/planning/plan", headers=h)).json()["result"]["selection"]
    assert set(sel["selected"]) == {a, b} and sel["using"] == "own"


async def test_use_selection_switches_and_keeps_the_options(client: AsyncClient) -> None:
    co = await make_company("plan-use")
    h = await headers_for(client, co)
    bolts = str(await fx.product(co.id, "B1", "Bolts"))
    cust = str(await fx.customer(co.id, "Use Ltd"))
    a = await _order(client, h, bolts, cust, "100", 10)
    extra = await _order(client, h, bolts, cust, "100", 12, mark=False)  # fits with no extra cost
    plan = (await client.get("/planning/plan", headers=h)).json()
    opts = plan["result"]["selection"]["options"]
    assert plan["result"]["selection"]["using"] == "own" and set(opts["part"]["orders"]) == {a, extra}

    r = (await client.patch(f"/planning/plans/{plan['id']}", headers=h, json={"use_option": "part"})).json()
    sel = r["plan"]["result"]["selection"]
    assert sel["using"] == "part" and set(sel["selected"]) == {a, extra}
    assert sel["options"]["own"]["orders"] == [a]  # your own picks stay, so the 3 options stay comparable
    assert (await client.get(f"/orders/{extra}", headers=h)).json()["marked_for_planning"]

    back = (await client.patch(f"/planning/plans/{plan['id']}", headers=h, json={"use_option": "own"})).json()
    assert back["plan"]["result"]["selection"]["using"] == "own"
    assert back["plan"]["result"]["selection"]["selected"] == [a]


async def test_new_order_after_approval_starts_the_next_plan(client: AsyncClient) -> None:
    co = await make_company("plan-next")
    h = await headers_for(client, co)
    bolts = str(await fx.product(co.id, "B1", "Bolts"))
    cust = str(await fx.customer(co.id, "Next Ltd"))
    await _order(client, h, bolts, cust, "100", 10)
    plan = (await client.get("/planning/plan", headers=h)).json()
    await client.post(f"/planning/plans/{plan['id']}/generate", headers=h)
    await client.post(f"/planning/plans/{plan['id']}/approve", headers=h, json={"raise_open_pos": True})

    await _order(client, h, bolts, cust, "100", 12, mark=False)  # a new accepted order, not sent yet
    still = (await client.get("/planning/plan", headers=h)).json()
    assert (
        still["number"] == plan["number"] and not still["needs_reapproval"]
    )  # unrelated order: no re-approval

    nxt = await _order(client, h, bolts, cust, "100", 14)  # sent to Planning
    cur = (await client.get("/planning/plan", headers=h)).json()
    assert (
        cur["number"] != plan["number"]
        and cur["status"] == "draft"
        and cur["result"]["selection"]["selected"] == [nxt]
    )


async def test_approval_does_not_trigger_its_own_reapproval(client: AsyncClient) -> None:
    co = await make_company("plan-appr")
    h = await headers_for(client, co)
    bolts = str(await fx.product(co.id, "B1", "Bolts", bom=[("STX", "Steel X", Decimal("0.01"))]))
    await fx.stock(co.id, "STX", Decimal("0"))  # short: approval raises a PO
    cust = str(await fx.customer(co.id, "Appr Ltd"))
    await _order(client, h, bolts, cust, "100", 10)
    await _order(client, h, bolts, cust, "100", 12, mark=False)  # another accepted order stays outside
    plan = (await client.get("/planning/plan", headers=h)).json()
    await client.post(f"/planning/plans/{plan['id']}/generate", headers=h)
    ap = (
        await client.post(f"/planning/plans/{plan['id']}/approve", headers=h, json={"raise_open_pos": True})
    ).json()
    assert ap["status"] == "approved" and not ap["needs_reapproval"]
    again = (await client.get("/planning/plan", headers=h)).json()
    assert again["status"] == "approved" and not again["needs_reapproval"]
