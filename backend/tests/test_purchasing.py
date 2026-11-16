"""Purchasing: inventory status rules, PO lifecycle (raise -> approve -> confirm -> receive / cancel),
the stock ledger, and the link with Planning (requests, deliveries on order)."""

from datetime import timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import clock
from app.core.config import get_settings
from app.core.db import set_tenant
from app.core.models import User
from seed import planning_demo
from seed.demo_data import seed_demo
from tests.conftest import AsyncClient, Company, headers_for, make_company


async def _demo_co(slug: str) -> Company:
    co = await make_company(slug)
    eng_ = create_async_engine(get_settings().database_owner_url)
    async with async_sessionmaker(eng_)() as s, s.begin():
        owner = (await s.execute(select(User.id).where(User.email == co.emails["owner"]))).scalar_one()
        await seed_demo(s, co.id, owner)
        await planning_demo.upsert(s, co.id)
    await eng_.dispose()
    return co


def _by_code(inv: dict) -> dict:  # type: ignore[type-arg]
    return {m["code"]: m for m in inv["materials"]}


async def test_inventory_status_rules_on_the_demo(client: AsyncClient) -> None:
    co = await _demo_co("pur-inv")
    h = await headers_for(client, co)
    # orders sent to Planning count even before anyone opens Planning (no plan made yet)
    early = _by_code((await client.get("/purchasing/inventory", headers=h)).json())
    assert early["WR8"]["status"] == "critical_short"
    await client.get("/planning/plan", headers=h)  # orders sent to Planning get a working plan
    inv = (await client.get("/purchasing/inventory", headers=h)).json()
    m = _by_code(inv)
    # critical short: 0.6 t in stock, ORD-1041 (in the plan being worked on) needs 3 t
    wr8 = m["WR8"]
    assert wr8["status"] == "critical_short" and wr8["reason"] == "Short by 2.4 t for ORD-1041 (Tata Motors)"
    assert float(wr8["shortfall"]["short"]) == 2.4
    assert float(wr8["suggested_qty"]) >= 2.4
    # low stock: below the reorder level, nothing needs it short
    assert m["SPS"]["status"] == "low_stock" and m["SPS"]["reason"] == "Below the reorder level of 2.5 t"
    # in transit: below reorder, a confirmed PO is on the way
    en8 = m["EN8"]
    assert en8["status"] == "in_transit" and float(en8["on_order"]) == 8.0
    assert en8["incoming"][0]["status"] == "confirmed" and en8["reason"].endswith("Shree Steels")
    assert m["BSW"]["status"] == "adequate"
    # nothing approved yet: nothing reserved
    assert all(float(x["reserved"]) == 0 for x in inv["materials"])
    k = inv["kpis"]
    assert (k["skus"], k["below_reorder"], k["on_order"], k["awaiting_approval"]) == (7, 3, 1, 0)
    assert k["stock_value_paise"] == sum(x["stock_value_paise"] for x in inv["materials"])
    assert [a["code"] for a in inv["attention"]] == ["WR8", "SPS", "EN8"]  # worst first
    # Planning reads the same delivery on order
    plan = (await client.get("/planning/plan", headers=h)).json()
    assert "EN8" not in {n["code"] for n in plan["result"]["purchase_needs"] if n.get("action")}


async def test_po_lifecycle_and_the_planning_link(client: AsyncClient) -> None:
    co = await _demo_co("pur-po")
    owner = await headers_for(client, co)
    buyer = await headers_for(client, co, "purchaser")
    planner = await headers_for(client, co, "planner")
    plan = (await client.get("/planning/plan", headers=owner)).json()
    pid = plan["id"]
    wr8 = next(n for n in plan["result"]["purchase_needs"] if n["code"] == "WR8")
    # Planning asked for the steel (Raise PO now in Final approval): a purchase request, no PO yet
    await client.post(
        f"/planning/plans/{pid}/purchase-requests", json={"material_id": wr8["material"]}, headers=owner
    )
    plan = (await client.get("/planning/plan", headers=owner)).json()
    line = next(c for c in plan["result"]["approval"]["checks"] if c.get("items"))["items"][0]["text"]
    assert "waiting for Purchasing to raise the PO" in line

    # the purchaser raises a PO: awaiting the owner's approval, not on order yet
    due = (clock.today() + timedelta(days=3)).isoformat()
    body = {"material_id": wr8["material"], "supplier": "Shree Steels", "quantity": "2.4",
            "price_per_unit_paise": 6_000_000, "expected_date": due}  # fmt: skip
    assert (await client.post("/purchasing/purchase-orders", json=body, headers=planner)).status_code == 403
    po = (await client.post("/purchasing/purchase-orders", json=body, headers=buyer)).json()
    assert po["status"] == "awaiting_approval" and po["source"] == "planning" and po["number"] == "PO-0002"
    inv = (await client.get("/purchasing/inventory", headers=owner)).json()
    w = _by_code(inv)["WR8"]
    assert (
        float(w["on_order"]) == 0 and float(w["awaiting_approval"]) == 2.4 and w["status"] == "critical_short"
    )
    assert inv["kpis"]["awaiting_approval"] == 1
    plan = (await client.get("/planning/plan", headers=owner)).json()
    line = next(c for c in plan["result"]["approval"]["checks"] if c.get("items"))["items"][0]["text"]
    assert "PO-0002 awaiting approval" in line

    # only the owner approves; then it's on order and Planning sees the delivery
    assert (
        await client.post(f"/purchasing/purchase-orders/{po['id']}/approve", headers=buyer)
    ).status_code == 403
    po = (await client.post(f"/purchasing/purchase-orders/{po['id']}/approve", headers=owner)).json()
    assert po["status"] == "ordered" and po["approved_at"]
    w = _by_code((await client.get("/purchasing/inventory", headers=owner)).json())["WR8"]
    assert float(w["on_order"]) == 2.4 and w["status"] in ("in_transit", "critical_short")

    # the supplier confirms a date
    due2 = (clock.today() + timedelta(days=2)).isoformat()
    po = (await client.post(f"/purchasing/purchase-orders/{po['id']}/confirm", json={"expected_date": due2},
                            headers=buyer)).json()  # fmt: skip
    assert po["status"] == "confirmed" and po["confirmed"] and po["expected_date"] == due2

    # receive part, then the rest: stock goes up through the ledger; over-receiving is refused
    lid = po["lines"][0]["id"]
    rec = f"/purchasing/purchase-orders/{po['id']}/receive"
    po = (await client.post(rec, json={"line_id": lid, "quantity": "1.0"}, headers=buyer)).json()
    assert po["status"] == "confirmed" and float(po["lines"][0]["received_qty"]) == 1.0
    assert (
        float(_by_code((await client.get("/purchasing/inventory", headers=owner)).json())["WR8"]["in_stock"])
        == 1.6
    )
    bad = await client.post(rec, json={"line_id": lid, "quantity": "5"}, headers=buyer)
    assert bad.status_code == 400 and "still to come" in bad.json()["error"]["message"]
    po = (await client.post(rec, json={"line_id": lid, "quantity": "1.4"}, headers=buyer)).json()
    assert po["status"] == "received"
    w = _by_code((await client.get("/purchasing/inventory", headers=owner)).json())["WR8"]
    assert float(w["in_stock"]) == 3.0 and float(w["on_order"]) == 0 and w["status"] != "critical_short"
    # received POs can't be cancelled
    c = await client.post(
        f"/purchasing/purchase-orders/{po['id']}/cancel", json={"reason": "x"}, headers=buyer
    )
    assert c.status_code == 400


async def test_cancel_hands_the_request_back_and_reserved_comes_from_approved_plans(
    client: AsyncClient,
) -> None:
    co = await _demo_co("pur-cancel")
    owner = await headers_for(client, co)
    plan = (await client.get("/planning/plan", headers=owner)).json()
    wr8 = next(n for n in plan["result"]["purchase_needs"] if n["code"] == "WR8")
    await client.post(f"/planning/plans/{plan['id']}/purchase-requests", json={"material_id": wr8["material"]},
                      headers=owner)  # fmt: skip
    body = {"material_id": wr8["material"], "supplier": "New Steel Co", "quantity": "2.4",
            "price_per_unit_paise": 100, "expected_date": (clock.today() + timedelta(days=5)).isoformat()}  # fmt: skip
    po = (await client.post("/purchasing/purchase-orders", json=body, headers=owner)).json()
    assert "New Steel Co" in (await client.get("/purchasing/inventory", headers=owner)).json()["suppliers"]
    assert (await client.post(f"/purchasing/purchase-orders/{po['id']}/cancel", json={"reason": ""},
                              headers=owner)).status_code == 422  # fmt: skip
    po = (await client.post(f"/purchasing/purchase-orders/{po['id']}/cancel", json={"reason": "Wrong supplier"},
                            headers=owner)).json()  # fmt: skip
    assert po["status"] == "cancelled" and po["cancel_reason"] == "Wrong supplier"
    plan = (await client.get("/planning/plan", headers=owner)).json()
    line = next(c for c in plan["result"]["approval"]["checks"] if c.get("items"))["items"][0]["text"]
    assert "waiting for Purchasing to raise the PO" in line  # the request is open again
    past = {**body, "expected_date": (clock.today() - timedelta(days=1)).isoformat()}
    assert (await client.post("/purchasing/purchase-orders", json=past, headers=owner)).status_code == 400

    # approve the plan: its orders' material is now reserved (stock set aside for them)
    await client.post(f"/planning/plans/{plan['id']}/generate", headers=owner)
    await client.post(f"/planning/plans/{plan['id']}/approve", json={"raise_open_pos": True}, headers=owner)
    m = _by_code((await client.get("/purchasing/inventory", headers=owner)).json())
    assert float(m["BSW"]["reserved"]) > 0  # ORD-1040 (M10 bolts) uses boron steel wire
    assert float(m["BSW"]["free"]) == float(m["BSW"]["in_stock"]) - float(m["BSW"]["reserved"])


async def test_stock_ledger_is_insert_only_for_the_app(client: AsyncClient) -> None:
    co = await _demo_co("pur-ledger")
    eng_ = create_async_engine(get_settings().database_url)  # the app's own role
    for sql in ("UPDATE stock_movements SET quantity = 0", "DELETE FROM stock_movements"):
        async with async_sessionmaker(eng_)() as s, s.begin():
            await set_tenant(s, co.id)
            with pytest.raises(DBAPIError, match="permission denied"):
                await s.execute(text(sql))
    await eng_.dispose()


async def test_accountant_reads_planner_cannot_raise(client: AsyncClient) -> None:
    co = await make_company("pur-perm")
    acc = await headers_for(client, co, "accountant")
    assert (await client.get("/purchasing/inventory", headers=acc)).status_code == 200
    assert (await client.get("/purchasing/purchase-orders", headers=acc)).status_code == 200
