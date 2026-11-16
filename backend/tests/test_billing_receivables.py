"""Billing > Receivables: outstanding is computed from receipts, three dates kept apart, as-of months reproduce."""

from datetime import timedelta

from httpx import AsyncClient

from app.core import clock
from tests.conftest import headers_for
from tests.test_purchasing import _demo_co

AR = "/billing/receivables"


async def test_outstanding_is_computed_and_moves_everywhere(client: AsyncClient) -> None:
    co = await _demo_co("bill-ar")
    owner = await headers_for(client, co)
    acc = await headers_for(client, co, "accountant")
    out = (await client.get(AR, headers=acc)).json()
    c = out["cards"]
    assert c["total_paise"] == sum(r["outstanding_paise"] for r in out["rows"]) > 0
    assert c["overdue_paise"] <= c["total_paise"] and out["counts"]["all"] == len(out["rows"])
    row = out["rows"][0]  # biggest outstanding first
    assert all(row["outstanding_paise"] >= r["outstanding_paise"] for r in out["rows"])
    cust = (await client.get(f"{AR}/customers/{row['customer_id']}", headers=acc)).json()
    inv = cust["invoices"][0]
    assert inv["outstanding_paise"] == inv["total_paise"] - inv["received_paise"] > 0
    # the customer profile (Orders > Customers) reads the same numbers
    prof = (await client.get(f"/customers/{row['customer_id']}", headers=owner)).json()
    same = next(i for i in prof["invoices"] if i["id"] == inv["id"])
    assert same["balance_due_paise"] == inv["outstanding_paise"]

    # a receipt changes every number that shows it
    part = inv["outstanding_paise"] // 2
    today = clock.today().isoformat()
    body = {"amount_paise": part, "received_on": today, "method": "neft", "reference": "UTR123456"}
    r = await client.post(f"{AR}/invoices/{inv['id']}/receipts", json=body, headers=acc)
    assert r.status_code == 201, r.text
    again = next(i for i in r.json()["invoices"] if i["id"] == inv["id"])
    assert again["outstanding_paise"] == inv["outstanding_paise"] - part and again["part_paid"]
    out2 = (await client.get(AR, headers=acc)).json()
    assert out2["cards"]["total_paise"] == c["total_paise"] - part
    assert out2["cards"]["received_paise"] == c["received_paise"] + part
    # the same UTR twice is the same money; more than outstanding is refused; no future receipts
    assert (
        await client.post(f"{AR}/invoices/{inv['id']}/receipts", json=body, headers=acc)
    ).status_code == 400
    too = body | {"reference": "X2", "amount_paise": again["outstanding_paise"] + 100}
    assert (
        await client.post(f"{AR}/invoices/{inv['id']}/receipts", json=too, headers=acc)
    ).status_code == 400
    fut = body | {"reference": "X3", "received_on": (clock.today() + timedelta(days=1)).isoformat()}
    assert (
        await client.post(f"{AR}/invoices/{inv['id']}/receipts", json=fut, headers=acc)
    ).status_code == 400
    # an advance adjusted reduces what is owed but isn't cash received this month
    adv = {"kind": "advance", "amount_paise": 100_00, "received_on": today}
    assert (
        await client.post(f"{AR}/invoices/{inv['id']}/receipts", json=adv, headers=acc)
    ).status_code == 201
    out3 = (await client.get(AR, headers=acc)).json()
    assert out3["cards"]["total_paise"] == out2["cards"]["total_paise"] - 100_00
    assert out3["cards"]["received_paise"] == out2["cards"]["received_paise"]
    # the planner can't see Billing; the purchaser reads only
    assert (await client.get(AR, headers=await headers_for(client, co, "planner"))).status_code == 403
    buyer = await headers_for(client, co, "purchaser")
    assert (await client.get(AR, headers=buyer)).status_code == 200
    assert (
        await client.post(f"{AR}/invoices/{inv['id']}/receipts", json=body, headers=buyer)
    ).status_code == 403


async def test_promises_follow_ups_and_past_months(client: AsyncClient) -> None:
    co = await _demo_co("bill-ar2")
    acc = await headers_for(client, co, "accountant")
    out = (await client.get(AR, headers=acc)).json()
    overdue = next(r for r in out["rows"] if r["status"] == "overdue")
    cust = (await client.get(f"{AR}/customers/{overdue['customer_id']}", headers=acc)).json()
    inv = next(i for i in cust["invoices"] if i["status"] == "overdue")
    due = inv["due_date"]
    p1 = {
        "amount_paise": inv["outstanding_paise"],
        "promised_on": (clock.today() + timedelta(days=3)).isoformat(),
    }
    r = await client.post(f"{AR}/invoices/{inv['id']}/promises", json=p1, headers=acc)
    assert r.status_code == 201, r.text
    p2 = p1 | {"promised_on": (clock.today() + timedelta(days=10)).isoformat(), "note": "Pushed by a week"}
    r = await client.post(f"{AR}/invoices/{inv['id']}/promises", json=p2, headers=acc)
    after = next(i for i in r.json()["invoices"] if i["id"] == inv["id"])
    # a new promise row each time; the due date never moves; a promise doesn't stop it being overdue
    assert [p["promised_on"] for p in after["promises"]] == [p2["promised_on"], p1["promised_on"]]
    assert (
        after["due_date"] == due
        and after["status"] == "overdue"
        and after["expected_on"] == p2["promised_on"]
    )
    past = (await client.post(f"{AR}/invoices/{inv['id']}/promises", headers=acc,
                              json=p1 | {"promised_on": (clock.today() - timedelta(days=1)).isoformat()})).status_code  # fmt: skip
    assert past == 400
    # follow-up: logged against the customer and the invoice, newest update on the row
    f = await client.post(f"{AR}/customers/{overdue['customer_id']}/follow-ups", headers=acc,
                          json={"invoice_id": inv["id"], "channel": "call", "note": "Spoke to accounts, cheque Friday"})  # fmt: skip
    assert f.status_code == 201 and f.json()["invoice_number"] == inv["number"]
    row = next(
        x
        for x in (await client.get(AR, headers=acc)).json()["rows"]
        if x["customer_id"] == overdue["customer_id"]
    )
    assert row["latest_update"].startswith("Call: Spoke to accounts")

    # last month's view is reproducible: a receipt today doesn't change it
    last = (clock.today().replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    before = (await client.get(f"{AR}?month={last}", headers=acc)).json()
    assert not before["period"]["live"]
    body = {"amount_paise": 1000_00, "received_on": clock.today().isoformat(), "reference": "PAST-TEST"}
    await client.post(f"{AR}/invoices/{inv['id']}/receipts", json=body, headers=acc)
    again = (await client.get(f"{AR}?month={last}", headers=acc)).json()
    assert again["cards"] == before["cards"]
    assert (await client.get(f"{AR}?month=2099-01", headers=acc)).status_code == 400
    csv_ = await client.get(f"{AR}/export", headers=acc)
    assert csv_.status_code == 200 and csv_.text.startswith("Customer,GSTIN")


async def test_money_history_is_insert_only_for_the_app(client: AsyncClient) -> None:
    import pytest
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.core.config import get_settings
    from app.core.db import set_tenant

    co = await _demo_co("bill-append")
    eng_ = create_async_engine(get_settings().database_url)  # the app's own role
    for t in ("invoice_receipts", "payment_promises", "interactions", "payable_events", "deal_events"):
        for sql in (f"UPDATE {t} SET created_at = now()", f"DELETE FROM {t}"):  # noqa: S608 (fixed table names)
            async with async_sessionmaker(eng_)() as s, s.begin():
                await set_tenant(s, co.id)
                with pytest.raises(DBAPIError, match="permission denied"):
                    await s.execute(text(sql))
    await eng_.dispose()
