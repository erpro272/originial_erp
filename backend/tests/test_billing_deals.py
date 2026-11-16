"""Billing > Invoice / E-bill: a deal per order and PO, derived status, draft -> verify -> issue (atomic: number,
lock, receivable), drafts never count, duplicates refused, documents and activity read from the real records."""

from httpx import AsyncClient

from app.core import clock
from tests.conftest import headers_for
from tests.test_purchasing import _demo_co

DEALS = "/billing/deals"


async def _deal_of(client: AsyncClient, h: dict[str, str], ref: str) -> dict:  # type: ignore[type-arg]
    rows = (await client.get(DEALS, headers=h)).json()["rows"]
    return next(r for r in rows if r["reference"] == ref)  # type: ignore[no-any-return]


async def _ship(client: AsyncClient, h: dict[str, str], order_id: str) -> None:
    for st in ("planned", "in_production", "completed", "shipped"):
        r = await client.patch(f"/orders/{order_id}", json={"status": st}, headers=h)
        assert r.status_code == 200 or "Already" in r.text, r.text


async def test_sale_deal_from_order_to_paid(client: AsyncClient) -> None:
    co = await _demo_co("bill-deal")
    owner = await headers_for(client, co)
    acc = await headers_for(client, co, "accountant")
    out = (await client.get(DEALS, headers=acc)).json()
    refs = {r["reference"] for r in out["rows"]}
    assert {"ORD-1036", "ORD-1041"} <= refs and all(r["number"].startswith("TXN-") for r in out["rows"])
    assert out["kpis"]["active"] <= out["kpis"]["total"] and out["kpis"]["documents_received"] > 0
    d = await _deal_of(client, acc, "ORD-1036")
    det = (await client.get(f"{DEALS}/{d['id']}", headers=acc)).json()
    assert det["row"]["kind"] == "sale" and det["row"]["status"] in ("Order Confirmed", "Awaiting Response")
    assert any(x["kind"] == "customer_po" and x["direction"] == "incoming" for x in det["documents"])
    # not dispatched: no invoice (production completion alone isn't a trigger)
    assert "No dispatch recorded yet" in det["invoice_block"]
    assert (await client.post(f"{DEALS}/{d['id']}/invoice", headers=acc)).status_code == 400

    await _ship(client, owner, det["order_id"])
    det = (await client.get(f"{DEALS}/{d['id']}", headers=acc)).json()
    assert det["row"]["status"] == "Dispatched" and det["invoice_block"] is None
    ar_before = (await client.get("/billing/receivables", headers=acc)).json()["cards"]["total_paise"]
    dr = (await client.post(f"{DEALS}/{d['id']}/invoice", headers=acc)).json()
    inv = dr["invoice"]
    assert inv["status"] == "draft" and inv["number"] is None and dr["row"]["status"] == "Invoice Pending"
    assert inv["cgst_paise"] + inv["sgst_paise"] + inv["igst_paise"] > 0
    # a draft is not a receivable and not counted as issued
    assert (await client.get("/billing/receivables", headers=acc)).json()["cards"]["total_paise"] == ar_before
    # one invoice per dispatch
    assert (await client.post(f"{DEALS}/{d['id']}/invoice", headers=acc)).status_code == 400
    # issue needs verification; an edit after verification clears it
    assert (await client.post(f"{DEALS}/{d['id']}/invoice/issue", headers=acc)).status_code == 400
    await client.post(f"{DEALS}/{d['id']}/invoice/verify", headers=acc)
    too_many = await client.patch(f"{DEALS}/{d['id']}/invoice", json={"quantity": "999999999"}, headers=acc)
    assert too_many.status_code == 400  # not more than was dispatched
    e = (
        await client.patch(f"{DEALS}/{d['id']}/invoice", json={"other_charges_paise": 500_00}, headers=acc)
    ).json()
    assert e["invoice"]["status"] == "draft" and e["invoice"]["other_charges_paise"] == 500_00
    await client.post(f"{DEALS}/{d['id']}/invoice/verify", headers=acc)
    # the purchaser can't issue; the accountant can
    buyer = await headers_for(client, co, "purchaser")
    assert (await client.post(f"{DEALS}/{d['id']}/invoice/issue", headers=buyer)).status_code == 403
    iss = (await client.post(f"{DEALS}/{d['id']}/invoice/issue", headers=acc)).json()
    num = iss["invoice"]["number"]
    fy = f"{clock.today().year if clock.today().month >= 4 else clock.today().year - 1}"
    assert iss["invoice"]["status"] == "issued" and num.startswith("DMC/") and fy in num
    assert iss["row"]["status"] == "Invoiced" and iss["invoice"]["due_date"]
    # issuing again has one effect; the issued invoice can't be edited
    again = (await client.post(f"{DEALS}/{d['id']}/invoice/issue", headers=acc)).json()
    assert again["invoice"]["number"] == num
    assert (
        await client.patch(f"{DEALS}/{d['id']}/invoice", json={"rate_paise": 1}, headers=acc)
    ).status_code == 400
    # the same record is now a receivable
    total = iss["invoice"]["total_paise"]
    assert (await client.get("/billing/receivables", headers=acc)).json()["cards"][
        "total_paise"
    ] == ar_before + total
    cust = (await client.get(f"/billing/receivables/customers/{det['customer_id']}", headers=acc)).json()
    rec = next(i for i in cust["invoices"] if i["number"] == num)
    assert rec["deal_number"] == d["number"]
    # archive refused while money is owed
    assert (await client.post(f"{DEALS}/{d['id']}/archive", headers=acc)).status_code == 400
    # send: an interaction on the deal; paid in full: Completed (dispatched and paid)
    sent = (
        await client.post(f"{DEALS}/{d['id']}/invoice/send", json={"channel": "email"}, headers=acc)
    ).json()
    assert sent["invoice"]["status"] == "sent" and sent["interactions"][0]["summary"].startswith(
        f"Invoice {num} sent"
    )
    await client.post(f"/billing/receivables/invoices/{rec['id']}/receipts", headers=acc,
                      json={"amount_paise": total, "received_on": clock.today().isoformat(), "reference": "UTR-FULL"})  # fmt: skip
    final = (await client.get(f"{DEALS}/{d['id']}", headers=acc)).json()
    assert final["row"]["status"] == "Completed" and final["invoice"]["outstanding_paise"] == 0
    titles = [a["title"] for a in final["activity"]]
    assert any(t.startswith(f"Invoice {num} issued") for t in titles) and any(
        "Payment received" in t for t in titles
    )
    assert (await client.post(f"{DEALS}/{d['id']}/archive", headers=acc)).json()["row"]["archived"]


async def test_create_deal_duplicates_and_purchase_deals(client: AsyncClient) -> None:
    co = await _demo_co("bill-deal2")
    acc = await headers_for(client, co, "accountant")
    cust = (await client.get("/customers?limit=1", headers=await headers_for(client, co))).json()
    name = cust["items"][0]["name"] if "items" in cust else cust[0]["name"]
    body = {"kind": "sale", "company": name, "item": "Bulk fastener assortment", "reference": "ENQ-0107",
            "quantity": "5000", "unit": "pcs"}  # fmt: skip
    r = await client.post(DEALS, json=body, headers=acc)
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["row"]["provisional"] and d["row"]["status"] == "Enquiry Received"
    assert "No order yet" in d["invoice_block"]
    # same company + same reference: blocked, pointing at the existing deal
    dup = await client.post(DEALS, json=body, headers=acc)
    assert dup.status_code == 409 and dup.json()["error"]["details"]["deal_id"] == d["row"]["id"]
    # same company + item + quantity within 30 days: a warning, then "create anyway"
    near = body | {"reference": None}
    w = await client.post(DEALS, json=near, headers=acc)
    assert w.status_code == 409 and w.json()["error"]["details"]["warning"]
    forced = await client.post(DEALS, json=near | {"force": True}, headers=acc)
    assert forced.status_code == 201
    # archived deals are not duplicates: once both are archived, the same enquiry goes through without a warning
    for x in (d["row"]["id"], forced.json()["row"]["id"]):
        assert (await client.post(f"{DEALS}/{x}/archive", headers=acc)).status_code == 200
    assert (await client.post(DEALS, json=near | {"item": body["item"]}, headers=acc)).status_code == 201
    # unknown company: never created on the fly
    assert (await client.post(DEALS, json=body | {"company": "Nobody Ltd"}, headers=acc)).status_code == 404
    # interactions on the deal
    i = await client.post(f"{DEALS}/{d['row']['id']}/interactions", headers=acc,
                          json={"channel": "whatsapp", "direction": "incoming", "summary": "Asked for the rate card"})  # fmt: skip
    assert i.status_code == 201
    assert (await client.get(f"{DEALS}/{d['row']['id']}", headers=acc)).json()["interactions"][0][
        "channel"
    ] == "whatsapp"
    # every PO is a purchase deal; Orders / Purchasing can show the TXN chip
    rows = (await client.get(DEALS, headers=acc)).json()["rows"]
    pur = next(r for r in rows if r["kind"] == "purchase")
    det = (await client.get(f"{DEALS}/{pur['id']}", headers=acc)).json()
    assert det["documents"][0]["kind"] == "purchase_order" and det["documents"][0]["direction"] == "outgoing"
    refs = (await client.get(f"/billing/deal-refs?po_id={det['po_id']}", headers=acc)).json()
    assert refs[det["po_id"]]["number"] == pur["number"]
