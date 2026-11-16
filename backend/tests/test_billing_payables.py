"""Billing > Payables: three-way match, owner approval can't be skipped, scheduled != paid, bank confirmation
settles, approver != executor (owner override logged), hold / reject / release."""

from datetime import timedelta
from decimal import Decimal

from httpx import AsyncClient

from app.core import clock
from tests.conftest import headers_for
from tests.test_purchasing import _by_code, _demo_co

AP = "/billing/payables"
PO = "/purchasing/purchase-orders"


def _d(n: int = 0) -> str:
    return (clock.today() + timedelta(days=n)).isoformat()


async def _received_po(client: AsyncClient, owner: dict[str, str], code: str, qty: str, accept: str) -> dict:  # type: ignore[type-arg]
    """A PO approved, at the gate and through QC (accept part, reject the rest)."""
    m = _by_code((await client.get("/purchasing/inventory", headers=owner)).json())
    body = {"material_id": m[code]["id"], "supplier": "Bill Test Steels", "quantity": qty,
            "price_per_unit_paise": 50_000_00, "expected_date": _d(3)}  # fmt: skip
    po = (await client.post(PO, json=body, headers=owner)).json()
    await client.post(f"{PO}/{po['id']}/approve", headers=owner)
    await client.post(
        f"{PO}/{po['id']}/gate-entry", json={"quantity": qty, "reference": "GRN-77"}, headers=owner
    )
    rej = str(Decimal(qty) - Decimal(accept))
    r = await client.post(f"{PO}/{po['id']}/qc", headers=owner,
                          json={"accepted": accept, "rejected": rej, "reason": "bent" if Decimal(rej) else None})  # fmt: skip
    assert r.status_code == 200, r.text
    return r.json()  # type: ignore[no-any-return]


async def test_three_way_match_and_the_approval_workflow(client: AsyncClient) -> None:
    co = await _demo_co("bill-ap")
    owner = await headers_for(client, co)
    acc = await headers_for(client, co, "accountant")
    po = await _received_po(client, owner, "BSW", "2", "1.8")  # QC accepted 1.8 t of 2 t
    inv = {"po_id": po["id"], "number": "BTS/26-27/101", "invoice_date": _d(), "quantity": "2",
           "rate_paise": 50_000_00, "gst_rate": "18"}  # fmt: skip
    r = await client.post(f"{AP}/invoices", json=inv, headers=acc)
    assert r.status_code == 201, r.text
    bad = r.json()
    assert bad["status"] == "pending_verif" and bad["stage"] == 2 and not bad["match_ok"]
    assert any("Bills 2 t but QC accepted 1.8 t" in m["text"] for m in bad["match"] if not m["ok"])
    assert bad["deal_number"] and bad["deal_number"].startswith("TXN-")
    # a mismatch blocks verification, and says what differs
    v = await client.post(f"{AP}/invoices/{bad['id']}/verify", headers=acc)
    assert v.status_code == 400 and "QC accepted 1.8 t" in v.json()["error"]["message"]
    # the same supplier invoice number twice is one invoice
    assert (await client.post(f"{AP}/invoices", json=inv, headers=acc)).status_code == 409
    # the owner rejects it (disputed: out of the payables total), the supplier sends a correct one
    rej = await client.post(
        f"{AP}/invoices/{bad['id']}/reject", json={"reason": "Bills 2 t, 1.8 t accepted"}, headers=owner
    )
    assert rej.json()["status"] == "rejected"
    good = (await client.post(f"{AP}/invoices", headers=acc,
                              json=inv | {"number": "BTS/26-27/102", "quantity": "1.8"})).json()  # fmt: skip
    assert good["match_ok"] and good["total_paise"] == 1_06_20_000  # 1.8 t x ₹50,000 + 18% GST
    sup = next(
        r for r in (await client.get(AP, headers=acc)).json()["rows"] if r["name"] == "Bill Test Steels"
    )
    assert sup["outstanding_paise"] == good["total_paise"] and sup["disputed_paise"] == bad["total_paise"]

    # accounts verify; accounts can't approve; the owner approves
    ok = (await client.post(f"{AP}/invoices/{good['id']}/verify", headers=acc)).json()
    assert ok["status"] == "pending_owner" and ok["stage"] == 3
    assert (await client.post(f"{AP}/invoices/{good['id']}/approve", headers=acc)).status_code == 403
    assert (await client.post(f"{AP}/invoices/{good['id']}/schedule", headers=acc,
                              json={"amount_paise": 100, "scheduled_for": _d(1)})).status_code == 400  # fmt: skip
    ap = (await client.post(f"{AP}/invoices/{good['id']}/approve", headers=owner)).json()
    assert (
        ap["status"] == "approved" and ap["outstanding_paise"] == good["total_paise"]
    )  # a decision, not money

    # scheduled is a plan: it never reduces what is owed
    half = good["total_paise"] // 2
    s = (await client.post(f"{AP}/invoices/{good['id']}/schedule", headers=acc,
                           json={"amount_paise": half, "scheduled_for": _d(2)})).json()  # fmt: skip
    assert s["status"] == "scheduled" and s["stage"] == 5 and s["outstanding_paise"] == good["total_paise"]
    over = await client.post(f"{AP}/invoices/{good['id']}/schedule", headers=acc,
                             json={"amount_paise": good["total_paise"], "scheduled_for": _d(2)})  # fmt: skip
    assert over.status_code == 400  # only the unscheduled balance
    pay = s["payments"][0]
    # the owner approved it: the owner can't also send the money without a logged reason
    e = await client.post(
        f"{AP}/payments/{pay['id']}/execute", json={"utr": "UTR0001", "executed_on": _d()}, headers=owner
    )
    assert e.status_code == 400 and "can't also execute" in e.json()["error"]["message"]
    x = (await client.post(f"{AP}/payments/{pay['id']}/execute", json={"utr": "UTR0001", "executed_on": _d()},
                           headers=acc)).json()  # fmt: skip
    assert x["stage"] == 6 and x["outstanding_paise"] == good["total_paise"]  # sent, not yet confirmed
    # the bank line must match; confirming it twice has one effect
    wrong = await client.post(f"{AP}/payments/{pay['id']}/bank-confirm", headers=acc,
                              json={"utr": "UTR0001", "amount_paise": half + 1, "confirmed_on": _d()})  # fmt: skip
    assert wrong.status_code == 400
    conf = {"utr": "UTR0001", "amount_paise": half, "confirmed_on": _d()}
    c1 = (await client.post(f"{AP}/payments/{pay['id']}/bank-confirm", json=conf, headers=acc)).json()
    c2 = (await client.post(f"{AP}/payments/{pay['id']}/bank-confirm", json=conf, headers=acc)).json()
    assert c1["outstanding_paise"] == good["total_paise"] - half == c2["outstanding_paise"]
    # the rest: owner override on execution, with a reason that is kept
    rest = good["total_paise"] - half
    s2 = (await client.post(f"{AP}/invoices/{good['id']}/schedule", headers=acc,
                            json={"amount_paise": rest, "scheduled_for": _d(1)})).json()  # fmt: skip
    p2 = next(p for p in s2["payments"] if p["status"] == "scheduled")
    o = (await client.post(f"{AP}/payments/{p2['id']}/execute", headers=owner,
                           json={"utr": "UTR0002", "executed_on": _d(), "override_reason": "Accountant on leave"})).json()  # fmt: skip
    assert next(p for p in o["payments"] if p["id"] == p2["id"])["override_reason"] == "Accountant on leave"
    done = (await client.post(f"{AP}/payments/{p2['id']}/bank-confirm", headers=acc,
                              json={"utr": "UTR0002", "amount_paise": rest, "confirmed_on": _d()})).json()  # fmt: skip
    assert done["status"] == "paid" and done["stage"] == 7 and done["outstanding_paise"] == 0
    actions = [ev["action"] for ev in done["events"]]
    assert actions[:4] == [
        "Invoice received",
        "Verified by accounts",
        "Approved by owner",
        "Payment scheduled",
    ]
    cards = (await client.get(AP, headers=acc)).json()["cards"]
    assert cards["paid_paise"] >= good["total_paise"]  # executed this month


async def test_hold_cancels_scheduled_and_release_goes_back_to_the_owner(client: AsyncClient) -> None:
    co = await _demo_co("bill-ap2")
    owner = await headers_for(client, co)
    acc = await headers_for(client, co, "accountant")
    po = await _received_po(client, owner, "SPS", "1", "1")
    inv = (await client.post(f"{AP}/invoices", headers=acc, json={
        "po_id": po["id"], "number": "H-1", "invoice_date": _d(), "quantity": "1", "rate_paise": 50_000_00})).json()  # fmt: skip
    await client.post(f"{AP}/invoices/{inv['id']}/verify", headers=acc)
    await client.post(f"{AP}/invoices/{inv['id']}/approve", headers=owner)
    s = (await client.post(f"{AP}/invoices/{inv['id']}/schedule", headers=acc,
                           json={"amount_paise": 1000_00, "scheduled_for": _d(1)})).json()  # fmt: skip
    assert (
        await client.post(f"{AP}/invoices/{inv['id']}/hold", json={"reason": "x"}, headers=acc)
    ).status_code == 403
    h = (
        await client.post(
            f"{AP}/invoices/{inv['id']}/hold", json={"reason": "Quality complaint"}, headers=owner
        )
    ).json()
    assert h["status"] == "on_hold" and h["payments"][0]["status"] == "cancelled"
    assert (await client.post(f"{AP}/payments/{s['payments'][0]['id']}/execute", headers=acc,
                              json={"utr": "UTR9", "executed_on": _d()})).status_code == 400  # fmt: skip
    rel = (
        await client.post(f"{AP}/invoices/{inv['id']}/release", json={"reason": "Resolved"}, headers=owner)
    ).json()
    assert rel["status"] == "pending_owner"  # back to approval, never straight to scheduled
    # unapproved invoices can't be scheduled by any call
    r = await client.post(f"{AP}/invoices/{inv['id']}/schedule", headers=acc,
                          json={"amount_paise": 1000_00, "scheduled_for": _d(1)})  # fmt: skip
    assert r.status_code == 400
