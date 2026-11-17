"""Supplier comparison: history from real PO steps (gate entry, QC), on-time vs the committed date, quotes,
the preferred supplier pre-filling Raise PO, the scoring rule and permissions."""

from datetime import date, timedelta

from sqlalchemy import update

from app.core import clock
from app.core.db import tenant_session
from app.purchasing.models import PurchaseOrder
from tests.conftest import AsyncClient, headers_for
from tests.test_purchasing import _by_code, _demo_co

PO = "/purchasing/purchase-orders"
CMP = "/purchasing/suppliers/comparison"


def _day(n: int) -> str:
    return (clock.today() + timedelta(days=n)).isoformat()


async def _deliver(client: AsyncClient, h: dict[str, str], tid, material_id: str, supplier: str, rate: int,  # type: ignore[no-untyped-def]
                   late: bool, rejected: str = "0") -> dict:  # type: ignore[type-arg]  # fmt: skip
    """Raise -> approve -> supplier confirms -> gate entry (on time or late) -> QC."""
    body = {"material_id": material_id, "supplier": supplier, "quantity": "1", "price_per_unit_paise": rate,
            "expected_date": _day(5)}  # fmt: skip
    po = (await client.post(PO, json=body, headers=h)).json()
    await client.post(f"{PO}/{po['id']}/approve", headers=h)
    # gate entries are stamped with the real time: promise a date that is ahead of both the pinned and the real date
    soon = max(clock.today(), date.today()) + timedelta(days=3)
    await client.post(f"{PO}/{po['id']}/confirm", json={"expected_date": soon.isoformat()}, headers=h)
    if late:  # the committed date has passed (and a follow-up moving the expected date doesn't change that)
        async with tenant_session(tid) as s:
            await s.execute(update(PurchaseOrder).where(PurchaseOrder.id == po["id"])
                            .values(promised_date=clock.today() - timedelta(days=2)))  # fmt: skip
        await client.post(
            f"{PO}/{po['id']}/follow-up", json={"note": "late", "promised_date": _day(0)}, headers=h
        )
    await client.post(f"{PO}/{po['id']}/gate-entry", json={"quantity": "1", "reference": "CH"}, headers=h)
    acc = str(1 - float(rejected))
    r = await client.post(f"{PO}/{po['id']}/qc", headers=h,
                          json={"accepted": acc, "rejected": rejected, "reason": "bad" if rejected != "0" else None})  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_history_scores_quotes_and_preferred(client: AsyncClient) -> None:
    co = await _demo_co("sup-cmp")
    owner = await headers_for(client, co)
    buyer = await headers_for(client, co, "purchaser")
    m = _by_code((await client.get("/purchasing/inventory", headers=owner)).json())
    sps = m["SPS"]["id"]
    # Good Strips: on time, clean QC, a bit dearer. Cheap Strips: late, 20% rejected, cheaper.
    for _ in range(2):
        await _deliver(client, owner, co.id, sps, "Good Strips", 60_000_00, late=False)
    await _deliver(client, owner, co.id, sps, "Cheap Strips", 50_000_00, late=True, rejected="0.2")
    out = (await client.get(CMP, headers=buyer)).json()
    rows = {r["supplier"]: r for r in out["rows"] if r["code"] == "SPS"}
    good, cheap = rows["Good Strips"], rows["Cheap Strips"]
    assert good["on_time_pct"] == 100.0 and good["defect_pct"] == 0.0 and good["quality_score"] == 10.0
    assert cheap["on_time_pct"] == 0.0 and cheap["defect_pct"] == 20.0 and cheap["quality_score"] == 0.0
    assert good["deliveries"] == 2 and good["lead_source"] == "actual" and good["rate_source"] == "last_po"
    assert set(cheap["flags"]) >= {"Late risk", "Quality risk"}
    assert good["overall"] > cheap["overall"]
    badges = {b: c["row"]["supplier"] for c in out["top"][sps] for b in c["badges"]}
    assert badges == {
        "Best overall": "Good Strips",
        "Highest quality": "Good Strips",
        "Lowest cost": "Cheap Strips",
    }
    assert out["kpis"]["active_suppliers"] >= 2 and out["kpis"]["avg_on_time_pct"] is not None

    # a quote request, then the reply: a new supplier rated on its quote only
    qs = (await client.post("/purchasing/quotes", headers=buyer,
                            json={"material_id": sps, "suppliers": ["New Strips"], "quantity": "2"})).json()  # fmt: skip
    assert qs[0]["status"] == "requested"
    out = (await client.get(CMP, headers=buyer)).json()
    assert any(q["id"] == qs[0]["id"] and q["status"] == "requested" for q in out["quotes"])
    bad = await client.post(f"/purchasing/quotes/{qs[0]['id']}/reply", headers=buyer,
                            json={"rate_paise": 55_000_00, "lead_days": 4, "valid_until": _day(-1)})  # fmt: skip
    assert bad.status_code == 400  # an expired quote
    r = await client.post(f"/purchasing/quotes/{qs[0]['id']}/reply", headers=buyer,
                          json={"rate_paise": 55_000_00, "lead_days": 4, "valid_until": _day(30)})  # fmt: skip
    assert r.json()["status"] == "received"
    new = next(r for r in (await client.get(CMP, headers=buyer)).json()["rows"]
               if r["supplier"] == "New Strips" and r["code"] == "SPS")  # fmt: skip
    assert new["rate_source"] == "quote" and new["lead_source"] == "quote" and new["lead_days"] == 4.0
    assert "No history yet" in new["flags"] and new["on_time_pct"] is None

    # Select vendor: Raise PO on the Inventory tab now pre-fills it and its rate
    sel = await client.put("/purchasing/preferred", headers=buyer,
                           json={"material_id": sps, "supplier_id": new["supplier_id"]})  # fmt: skip
    assert sel.status_code == 200 and sel.json()["preferred"]
    inv = _by_code((await client.get("/purchasing/inventory", headers=owner)).json())["SPS"]
    assert inv["supplier"] == "New Strips" and inv["preferred"] and inv["preferred_rate_paise"] == 55_000_00


async def test_scoring_rule_is_the_owners_and_reads_are_open_to_purchasing(client: AsyncClient) -> None:
    co = await _demo_co("sup-rule")
    owner = await headers_for(client, co)
    buyer = await headers_for(client, co, "purchaser")
    acc = await headers_for(client, co, "accountant")
    planner = await headers_for(client, co, "planner")
    rules = (await client.get("/purchasing/scoring-rules", headers=buyer)).json()
    assert rules["price_weight"] == 40 and rules["late_risk_below"] == 90
    assert (await client.put("/purchasing/scoring-rules", headers=buyer, json=rules)).status_code == 403
    zero = rules | {"price_weight": 0, "on_time_weight": 0, "quality_weight": 0, "lead_weight": 0}
    assert (await client.put("/purchasing/scoring-rules", headers=owner, json=zero)).status_code == 400
    r = await client.put("/purchasing/scoring-rules", headers=owner, json=rules | {"price_weight": 70})
    assert r.status_code == 200 and (await client.get(CMP, headers=acc)).json()["rules"]["price_weight"] == 70
    assert (await client.get(CMP, headers=planner)).status_code == 200
    m = _by_code((await client.get("/purchasing/inventory", headers=owner)).json())
    q = await client.post(
        "/purchasing/quotes", headers=acc, json={"material_id": m["SPS"]["id"], "suppliers": ["X"]}
    )
    assert q.status_code == 403  # the accountant reads only
