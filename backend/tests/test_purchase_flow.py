"""Raw Material Purchase: stages (pending, sent, delayed, arriving today, at the gate), priority from the linked
order, KPIs and attention, edits before approval, follow-ups, the PO timeline and the event for Production."""

from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core import clock
from app.core.config import get_settings
from app.core.db import set_tenant, tenant_session
from app.core.models import OutboxEvent
from app.purchasing.models import PurchaseOrder
from tests.conftest import AsyncClient, headers_for
from tests.test_purchasing import _by_code, _demo_co

PO = "/purchasing/purchase-orders"


def _day(n: int) -> str:
    return (clock.today() + timedelta(days=n)).isoformat()


async def _set_expected(tid, number: str, days: int) -> None:  # type: ignore[no-untyped-def]
    """Move a PO's expected date (e.g. into the past) the way time passing would."""
    async with tenant_session(tid) as s:
        await s.execute(update(PurchaseOrder).where(PurchaseOrder.number == number)
                        .values(expected_date=clock.today() + timedelta(days=days)))  # fmt: skip


async def test_stages_priority_kpis_and_attention(client: AsyncClient) -> None:
    co = await _demo_co("buy-stages")
    owner = await headers_for(client, co)
    buyer = await headers_for(client, co, "purchaser")
    inv = (await client.get("/purchasing/inventory", headers=owner)).json()
    m = _by_code(inv)
    # the orders that need a material are offered for linking
    assert "ORD-1041" in [n["number"] for n in m["WR8"]["needs"]]

    async def raise_(code: str, qty: str, days: int, orders: list[str], prio: str | None = None) -> dict:  # type: ignore[type-arg]
        body = {"material_id": m[code]["id"], "supplier": "Test Steels", "quantity": qty,
                "price_per_unit_paise": 100_000_00, "expected_date": _day(days), "order_numbers": orders,
                "priority": prio}  # fmt: skip
        r = await client.post(PO, json=body, headers=buyer)
        assert r.status_code == 201, r.text
        return r.json()  # type: ignore[no-any-return]

    # linked to ORD-1041 (high priority in the demo), delivery 30 days out: later than the order needs it
    late = await raise_("WR8", "2.4", 30, ["ORD-1041"])
    assert late["stage"] == "pending_approval" and late["priority"] == "high" and late["needed_by"]
    assert "after the order needs it" in late["stage_text"]
    # no linked order: the purchaser's priority
    plain = await raise_("BSW", "1", 5, [], "low")
    assert plain["priority"] == "low" and plain["orders"] == []
    bad = await client.post(PO, json={"material_id": m["BSW"]["id"], "supplier": "X", "quantity": "1",
                                      "price_per_unit_paise": 1, "expected_date": _day(3),
                                      "order_numbers": ["ORD-9999"]}, headers=buyer)  # fmt: skip
    assert bad.status_code == 400 and "ORD-9999" in bad.json()["error"]["message"]

    for p in (late, plain):
        assert (await client.post(f"{PO}/{p['id']}/approve", headers=owner)).status_code == 200
    # sent, then behind schedule vs the order -> delayed
    got = (await client.get(f"{PO}/{late['id']}", headers=owner)).json()
    assert got["stage"] == "delayed" and "behind schedule (after the order needs it)" in got["stage_text"]
    # overdue: the expected date has passed and nothing arrived
    await _set_expected(co.id, plain["number"], -1)
    got = (await client.get(f"{PO}/{plain['id']}", headers=owner)).json()
    assert got["stage"] == "delayed" and got["stage_text"] == "1 day behind schedule (overdue)"
    # arriving today
    await _set_expected(co.id, plain["number"], 0)
    got = (await client.get(f"{PO}/{plain['id']}", headers=owner)).json()
    assert got["stage"] == "arriving_today"
    # dispatched later in the week: in transit
    await _set_expected(co.id, plain["number"], 3)
    got = (await client.post(f"{PO}/{plain['id']}/dispatch", json={}, headers=buyer)).json()
    assert got["stage"] == "in_transit"

    pending = await raise_("MSB", "1", 4, [])
    out = (await client.get("/purchasing/purchases", headers=owner)).json()
    k = out["kpis"]
    open_ = [p for p in out["purchase_orders"] if p["status"] not in ("received", "cancelled")]
    assert k["open"] == len(open_) and k["pending_approval"] == 1 and k["in_transit"] == 1
    assert k["open_spend_paise"] == sum(p["open_value_paise"] for p in open_) > 0
    # attention: action required first, then delayed
    stages = [p["stage"] for p in out["attention"]]
    assert stages[0] == "pending_approval" and out["attention"][0]["number"] == pending["number"]
    assert "delayed" in stages and "in_transit" not in stages
    assert "Test Steels" in out["suppliers"]


async def test_edit_before_approval_follow_up_and_timeline(client: AsyncClient) -> None:
    co = await _demo_co("buy-edit")
    owner = await headers_for(client, co)
    buyer = await headers_for(client, co, "purchaser")
    m = _by_code((await client.get("/purchasing/inventory", headers=owner)).json())
    body = {"material_id": m["SPS"]["id"], "supplier": "Jindal Strips", "quantity": "1",
            "price_per_unit_paise": 50_000_00, "expected_date": _day(6)}  # fmt: skip
    po = (await client.post(PO, json=body, headers=buyer)).json()
    po = (await client.patch(f"{PO}/{po['id']}", json={"quantity": "1.5", "order_numbers": ["ORD-1043"]},
                             headers=buyer)).json()  # fmt: skip
    assert float(po["lines"][0]["quantity"]) == 1.5 and po["orders"] == ["ORD-1043"]
    assert po["events"][-1]["summary"].startswith("Changed · quantity 1.5 t, linked orders ORD-1043")
    await client.post(f"{PO}/{po['id']}/approve", headers=owner)
    r = await client.patch(f"{PO}/{po['id']}", json={"quantity": "2"}, headers=buyer)
    assert r.status_code == 400  # approved: no more edits
    # follow-up: note + the supplier's new date
    po = (await client.post(f"{PO}/{po['id']}/follow-up", json={"note": "Called Mr Rao", "promised_date": _day(9)},
                            headers=buyer)).json()  # fmt: skip
    assert po["expected_date"] == _day(9) and "supplier now promises" in po["events"][-1]["summary"]
    assert [e["kind"] for e in po["events"]] == ["raised", "edited", "approved", "follow_up"]
    # the timeline is insert-only for the app
    eng_ = create_async_engine(get_settings().database_url)
    for sql in ("UPDATE po_events SET summary = 'x'", "DELETE FROM po_events"):
        async with async_sessionmaker(eng_)() as s, s.begin():
            await set_tenant(s, co.id)
            with pytest.raises(DBAPIError, match="permission denied"):
                await s.execute(text(sql))
    await eng_.dispose()


async def test_qc_puts_stock_in_and_tells_production(client: AsyncClient) -> None:
    co = await _demo_co("buy-qc")
    owner = await headers_for(client, co)
    m = _by_code((await client.get("/purchasing/inventory", headers=owner)).json())
    body = {"material_id": m["AS10"]["id"], "supplier": "Mukand Wires", "quantity": "2",
            "price_per_unit_paise": 80_000_00, "expected_date": _day(2), "order_numbers": ["ORD-1036"]}  # fmt: skip
    po = (await client.post(PO, json=body, headers=owner)).json()
    await client.post(f"{PO}/{po['id']}/approve", headers=owner)
    await client.post(
        f"{PO}/{po['id']}/gate-entry", json={"quantity": "2", "reference": "CH-77"}, headers=owner
    )
    before = Decimal(m["AS10"]["in_stock"])
    po = (await client.post(f"{PO}/{po['id']}/qc", json={"accepted": "2"}, headers=owner)).json()
    assert po["status"] == "received"
    after = _by_code((await client.get("/purchasing/inventory", headers=owner)).json())["AS10"]
    assert Decimal(after["in_stock"]) == before + 2
    async with tenant_session(co.id) as s:
        ev = (
            await s.execute(select(OutboxEvent).where(OutboxEvent.type == "purchasing.material_received"))
        ).scalars()
        payloads = [e.payload for e in ev]
    assert payloads == [{"po": po["number"], "material_id": m["AS10"]["id"], "material": "AS10", "quantity": "2",
                         "unit": "t", "orders": ["ORD-1036"]}]  # fmt: skip
    # permissions: the accountant reads, can't act
    acc = await headers_for(client, co, "accountant")
    assert (await client.get("/purchasing/purchases", headers=acc)).status_code == 200
    assert (
        await client.post(f"{PO}/{po['id']}/follow-up", json={"note": "x"}, headers=acc)
    ).status_code == 403


async def test_demo_purchases_show_every_stage_without_changing_the_plan(client: AsyncClient) -> None:
    from seed.purchase_demo import seed_purchases

    co = await _demo_co("buy-demo")
    h = await headers_for(client, co)
    before = (await client.get("/planning/plan", headers=h)).json()["result"]["sequence"]["rows"]
    eng_ = create_async_engine(get_settings().database_owner_url)
    async with async_sessionmaker(eng_)() as s, s.begin():
        assert await seed_purchases(s, co.id) == 4
    async with async_sessionmaker(eng_)() as s, s.begin():
        assert await seed_purchases(s, co.id) == 0  # once only
    await eng_.dispose()
    out = (await client.get("/purchasing/purchases", headers=h)).json()
    stages = {p["lines"][0]["code"]: p["stage"] for p in out["purchase_orders"]}
    assert stages == {"WR8": "pending_approval", "BSW": "delayed", "MSB": "at_gate", "AS10": "sent",
                      "EN8": "confirmed"}  # fmt: skip
    assert [p["stage"] for p in out["attention"]] == ["pending_approval", "delayed", "at_gate"]
    assert out["attention"][0]["priority"] == "high"  # ORD-1041
    after = (await client.get("/planning/plan", headers=h)).json()["result"]["sequence"]["rows"]
    assert [(r["id"], r["start"], r["finish"]) for r in after] == [
        (r["id"], r["start"], r["finish"]) for r in before
    ]
