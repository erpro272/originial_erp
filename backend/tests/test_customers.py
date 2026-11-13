import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.core.db import tenant_session
from app.customers.health import health_tags, high_value_threshold, primary
from app.customers.models import Customer
from app.customers.schemas import HealthSettings
from app.customers.service import resolve_period
from app.invoices.stats import CustomerStats
from tests import factories as f
from tests.conftest import TODAY, Company, headers_for, make_company

GST_A = f.gstin("27", "AAACT2727Q")  # Maharashtra
GST_B = f.gstin("33", "AAACA4567F")  # Tamil Nadu


@pytest.fixture(scope="module")
async def client_mod(app, tenants):  # type: ignore[no-untyped-def]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api") as c:
        yield c


@pytest.fixture(scope="module")
async def co() -> Company:
    return await make_company("cust")


# ---- pure rules ----------------------------------------------------------------------------

P_FROM, P_TO = date(2026, 4, 1), TODAY
CFG = HealthSettings()


def st(**kw: object) -> CustomerStats:
    base = {
        "invoices_all": 3,
        "first_date": date(2025, 1, 1),
        "last_date": TODAY,
        "period_sales": 0,
        "prev_sales": 0,
    }
    return CustomerStats(**(base | kw))  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("days", "expected"),
    [(59, "repeat"), (60, "inactive"), (89, "inactive"), (90, "dormant"), (400, "dormant")],
)
def test_recency_boundaries(days: int, expected: str) -> None:
    tags = health_tags(st(last_date=TODAY - timedelta(days=days)), CFG, TODAY, P_FROM, P_TO, None)
    assert primary(tags) == expected


def test_inactive_needs_previous_regular_buying() -> None:
    one_off = st(invoices_all=1, first_date=TODAY - timedelta(days=400), last_date=TODAY - timedelta(days=70))
    assert health_tags(one_off, CFG, TODAY, P_FROM, P_TO, None) == []


def test_new_declining_high_value() -> None:
    assert "new" in health_tags(st(first_date=P_FROM, invoices_all=1), CFG, TODAY, P_FROM, P_TO, None)
    assert "new" not in health_tags(st(first_date=P_FROM - timedelta(days=1)), CFG, TODAY, P_FROM, P_TO, None)
    # declining: below 70% of the previous period (boundary at exactly 70% is not declining)
    assert "declining" in health_tags(st(period_sales=69, prev_sales=100), CFG, TODAY, P_FROM, P_TO, None)
    assert "declining" not in health_tags(st(period_sales=70, prev_sales=100), CFG, TODAY, P_FROM, P_TO, None)
    assert "high_value" in health_tags(st(period_sales=500), CFG, TODAY, P_FROM, P_TO, 500)
    assert primary(["repeat", "high_value", "declining"]) == "declining"


def test_high_value_threshold_top_10_pct() -> None:
    sales = list(range(1, 21))  # 20 buying customers -> top 2
    assert high_value_threshold([*sales, 0, 0], 10) == 19
    assert high_value_threshold([5], 10) == 5
    assert high_value_threshold([0, 0], 10) is None


def test_periods() -> None:
    fytd = resolve_period("fytd", None, None, TODAY)
    assert (fytd.date_from, fytd.date_to) == (date(2026, 4, 1), TODAY)
    assert fytd.prev_to == date(2026, 3, 31) and (fytd.prev_to - fytd.prev_from) == (
        fytd.date_to - fytd.date_from
    )
    q = resolve_period("this_quarter", None, None, TODAY)
    assert q.date_from == date(2026, 10, 1)
    assert resolve_period("this_quarter", None, None, date(2027, 2, 10)).date_from == date(2027, 1, 1)
    assert resolve_period("this_month", None, None, TODAY).date_from == date(2026, 11, 1)


# ---- master data via API -------------------------------------------------------------------


async def test_create_fills_pan_and_state_from_gstin(client_mod: AsyncClient, co: Company) -> None:
    h = await headers_for(client_mod, co)
    r = await client_mod.post("/customers", headers=h, json={"name": "Tata Motors", "gstin": GST_A.lower()})
    assert r.status_code == 201, r.text
    d = (await client_mod.get(f"/customers/{r.json()['id']}", headers=h)).json()
    assert (
        d["row"]["gstin"] == GST_A and d["row"]["pan"] == "AAACT2727Q" and d["row"]["state"] == "Maharashtra"
    )


@pytest.mark.parametrize(
    ("body", "field", "fragment"),
    [
        ({"gstin": GST_B[:-1] + ("A" if GST_B[-1] != "A" else "B")}, "gstin", "checksum"),
        ({"gstin": "27AAACT2727Q1Z"}, "gstin", "15 characters"),
        ({"gstin": GST_B, "pan": "AAACT2727Q"}, "pan", "doesn't match"),
        ({"gstin": GST_B, "state_code": "27"}, "state_code", "doesn't match"),
        ({"pan": "ABC"}, "pan", "invalid"),
    ],
)
async def test_identity_validation(
    client_mod: AsyncClient, co: Company, body: dict, field: str, fragment: str
) -> None:  # type: ignore[type-arg]
    h = await headers_for(client_mod, co)
    r = await client_mod.post("/customers", headers=h, json={"name": "Bad Co"} | body)
    assert r.status_code == 400
    assert fragment in r.json()["error"]["details"]["fields"][field]


async def test_gstin_unique_per_company_not_globally(client_mod: AsyncClient, co: Company) -> None:
    h = await headers_for(client_mod, co)
    await client_mod.post("/customers", headers=h, json={"name": "Ashok Leyland", "gstin": GST_B})
    dup = await client_mod.post("/customers", headers=h, json={"name": "Ashok L.", "gstin": GST_B})
    assert dup.status_code == 409 and "Ashok Leyland" in dup.json()["error"]["message"]
    other = await make_company("cust-other")
    h2 = await headers_for(client_mod, other)
    assert (
        await client_mod.post("/customers", headers=h2, json={"name": "Ashok", "gstin": GST_B})
    ).status_code == 201


async def test_bank_account_encrypted_and_masked_by_role(client_mod: AsyncClient, co: Company) -> None:
    h = await headers_for(client_mod, co)
    body = {"name": "Mahindra", "bank_name": "HDFC Bank", "bank_ifsc": "HDFC0001234",
            "bank_account": "50100123454417", "upi_id": "mahindra@okhdfc"}  # fmt: skip
    cid = (await client_mod.post("/customers", headers=h, json=body)).json()["id"]
    async with tenant_session(co.id) as s:
        c = (await s.execute(select(Customer).where(Customer.id == uuid.UUID(cid)))).scalar_one()
        assert c.bank_account_enc and b"50100123454417" not in c.bank_account_enc
        assert c.upi_enc and b"mahindra" not in c.upi_enc
    for role, account, upi, visible in [
        ("owner", "50100123454417", "mahindra@okhdfc", True),
        ("accountant", "50100123454417", "mahindra@okhdfc", True),
        ("planner", "XXXXXXXXXX4417", "XXXXXXra@okhdfc", False),
        ("purchaser", "XXXXXXXXXX4417", "XXXXXXra@okhdfc", False),
    ]:
        d = (
            await client_mod.get(f"/customers/{cid}", headers=await headers_for(client_mod, co, role))
        ).json()
        assert (d["bank_account"], d["upi_id"], d["sensitive_visible"]) == (account, upi, visible), role
    log = (
        await client_mod.get("/audit-log", headers=h, params={"entity_type": "customer", "entity_id": cid})
    ).json()
    assert "50100123454417" not in str(log)


async def test_only_writers_create(client_mod: AsyncClient, co: Company) -> None:
    h = await headers_for(client_mod, co, "purchaser")
    assert (await client_mod.post("/customers", headers=h, json={"name": "X Co"})).status_code == 403


# ---- metrics, health, filters --------------------------------------------------------------


@pytest.fixture(scope="module")
async def book() -> tuple[Company, dict[str, uuid.UUID]]:
    co = await make_company("metrics")
    t = co.id
    ids = {
        "maruti": await f.customer(
            t, "Maruti Suzuki", gst=f.gstin("06", "AAACM1234A"), phone="+91 98100 12345"
        ),
        "tata": await f.customer(t, "Tata Motors", gst=GST_A),
        "tvs": await f.customer(t, "TVS Motor", gst=f.gstin("33", "AAACT5678G")),
        "escorts": await f.customer(t, "Escorts Kubota"),
        "none": await f.customer(t, "Never Bought"),
    }
    d = lambda n: f.ago(TODAY, n)  # noqa: E731
    # Maruti: big buyer, active, 2 in period + 1 before, part unpaid
    await f.invoice(t, ids["maruti"], d(5), 500_000, qty=5000, balance_rupees=100_000)
    await f.invoice(t, ids["maruti"], d(40), 300_000, qty=3000, uom="KG")  # KG not counted as units
    await f.invoice(t, ids["maruti"], date(2026, 1, 10), 200_000, qty=2000)
    # Tata: bought a lot in the previous period, little now -> declining
    await f.invoice(t, ids["tata"], date(2025, 10, 1), 400_000)
    await f.invoice(t, ids["tata"], date(2025, 12, 1), 400_000)
    await f.invoice(t, ids["tata"], d(20), 100_000, product_name="M8 nylock nuts")
    # TVS: regular buyer, last bought 78 days ago -> inactive
    await f.invoice(t, ids["tvs"], d(78), 50_000)
    await f.invoice(t, ids["tvs"], d(250), 50_000)  # first purchase before this FY
    # Escorts: first purchase in this period -> new
    await f.invoice(t, ids["escorts"], d(7), 80_000, qty=800)
    return co, ids


async def test_list_metrics_overview_and_health(client_mod: AsyncClient, book) -> None:  # type: ignore[no-untyped-def]
    co, _ids = book
    h = await headers_for(client_mod, co)
    page = (await client_mod.get("/customers", headers=h, params={"limit": 50})).json()
    rows = {r["name"]: r for r in page["items"]}
    m = rows["Maruti Suzuki"]
    assert (m["total_sales_paise"], m["invoices"], m["aov_paise"]) == (80_000_000, 2, 40_000_000)
    assert Decimal(m["units_sold"]) == 5000  # KG line excluded
    assert m["outstanding_paise"] == 10_000_000 and m["last_purchase"] == str(f.ago(TODAY, 5))
    assert m["lifetime_invoices"] == 3 and m["health"] == "high_value"
    assert rows["Tata Motors"]["health"] == "declining"
    assert rows["TVS Motor"]["health"] == "inactive" and rows["TVS Motor"]["days_since_last"] == 78
    assert rows["Escorts Kubota"]["health"] == "new"
    assert rows["Never Bought"]["health"] is None and rows["Never Bought"]["invoices"] == 0
    ov = page["overview"]
    assert ov["total_customers"] == 5 and ov["active_customers"] == 4 and ov["active_pct"] == 80.0
    assert ov["new_customers"] == 1 and Decimal(ov["units_sold"]) == 5000 + 100 + 100 + 800
    assert page["health_counts"]["all"] == 5 and page["health_counts"]["inactive"] == 1
    assert page["available_fields"] >= 30
    # default sort: total sales desc
    assert [r["name"] for r in page["items"]][:2] == ["Maruti Suzuki", "Tata Motors"]


@pytest.mark.parametrize(
    ("params", "names"),
    [
        ({"health": "inactive"}, ["TVS Motor"]),
        ({"health": ["new", "declining"]}, ["Tata Motors", "Escorts Kubota"]),
        ({"q": "maruti"}, ["Maruti Suzuki"]),
        ({"q": "98100"}, ["Maruti Suzuki"]),  # phone digits
        ({"q": GST_A}, ["Tata Motors"]),
        ({"state": "33"}, ["TVS Motor"]),
        ({"outstanding_only": True}, ["Maruti Suzuki"]),
        ({"product": "nylock"}, ["Tata Motors"]),
        ({"min_sales_paise": 9_000_000, "max_sales_paise": 20_000_000}, ["Tata Motors"]),
        (
            {"sort": "name", "desc": False},
            ["Escorts Kubota", "Maruti Suzuki", "Never Bought", "Tata Motors", "TVS Motor"],
        ),
    ],
)
async def test_filters(client_mod: AsyncClient, book, params, names) -> None:  # type: ignore[no-untyped-def]
    co, _ = book
    h = await headers_for(client_mod, co)
    r = await client_mod.get("/customers", headers=h, params=params | {"limit": 50})
    assert r.status_code == 200, r.text
    assert [x["name"] for x in r.json()["items"]] == names


async def test_period_changes_values(client_mod: AsyncClient, book) -> None:  # type: ignore[no-untyped-def]
    co, _ = book
    h = await headers_for(client_mod, co)
    month = (
        await client_mod.get("/customers", headers=h, params={"period": "this_month", "q": "maruti"})
    ).json()
    assert month["items"][0]["total_sales_paise"] == 50_000_000
    custom = await client_mod.get("/customers", headers=h, params={"period": "custom", "date_from": "2026-01-01",
                                                                    "date_to": "2026-01-31", "q": "maruti"})  # fmt: skip
    assert custom.json()["items"][0]["total_sales_paise"] == 20_000_000
    bad = await client_mod.get("/customers", headers=h, params={"period": "custom", "date_from": "2026-02-01",
                                                                 "date_to": "2026-01-01"})  # fmt: skip
    assert bad.status_code == 400


async def test_profile_detail(client_mod: AsyncClient, book) -> None:  # type: ignore[no-untyped-def]
    co, ids = book
    h = await headers_for(client_mod, co)
    d = (await client_mod.get(f"/customers/{ids['maruti']}", headers=h)).json()
    assert len(d["invoices"]) == 3 and d["invoices"][0]["status"] == "partial"
    assert sum(p["sales_paise"] for p in d["monthly_sales"]) == 100_000_000
    assert d["top_products"][0]["name"] == "M10 hex bolts"


async def test_followups(client_mod: AsyncClient, book) -> None:  # type: ignore[no-untyped-def]
    co, ids = book
    h = await headers_for(client_mod, co, "planner")  # any role can log follow-ups
    url = f"/customers/{ids['tvs']}/followups"
    assert (await client_mod.post(url, headers=h, json={"kind": "reminder"})).status_code == 400
    r = await client_mod.post(
        url, headers=h, json={"kind": "reminder", "note": "Call about Q4", "due_date": str(TODAY)}
    )
    assert r.status_code == 201 and r.json()["done_at"] is None
    call = await client_mod.post(url, headers=h, json={"kind": "call", "note": "Spoke to purchase head"})
    assert call.json()["done_at"] is not None
    due = (await client_mod.get("/customers", headers=h, params={"followups_due": True})).json()
    assert [x["name"] for x in due["items"]] == ["TVS Motor"] and due["items"][0]["open_followups"] == 1
    await client_mod.post(f"{url}/{r.json()['id']}/done", headers=h)
    assert (await client_mod.get("/customers", headers=h, params={"followups_due": True})).json()[
        "total"
    ] == 0


async def test_merge(client_mod: AsyncClient) -> None:
    co = await make_company("merge")
    t = co.id
    h = await headers_for(client_mod, co)
    keep = await f.customer(t, "Hero MotoCorp Ltd", gst=f.gstin("07", "AAACH3456E"))
    dup = await f.customer(t, "Hero Motocorp", phone="9999911111")
    await f.invoice(t, keep, f.ago(TODAY, 3), 1000)
    await f.invoice(t, dup, f.ago(TODAY, 4), 2000)
    other = await f.customer(t, "Other GST", gst=f.gstin("07", "AAACZ9999Z"))
    r = await client_mod.post(f"/customers/{keep}/merge", headers=h, json={"source_id": str(other)})
    assert r.status_code == 400  # different GSTINs = different businesses
    r = await client_mod.post(f"/customers/{keep}/merge", headers=h, json={"source_id": str(dup)})
    assert r.status_code == 200
    page = (await client_mod.get("/customers", headers=h, params={"q": "hero", "limit": 50})).json()
    assert [x["name"] for x in page["items"]] == ["Hero MotoCorp Ltd"]
    assert page["items"][0]["lifetime_invoices"] == 2 and page["items"][0]["phone"] == "9999911111"
    assert (await client_mod.get(f"/customers/{dup}", headers=h)).status_code == 404
