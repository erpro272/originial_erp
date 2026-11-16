import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from httpx import AsyncClient

from app.orders.service import working_days_between
from tests import factories as f
from tests.conftest import TODAY, Company, headers_for, make_company


@pytest.fixture(scope="module")
async def co() -> Company:
    return await make_company("orders")


@pytest.fixture(scope="module")
async def data(co: Company) -> dict[str, uuid.UUID]:
    t = co.id
    bolts = await f.product(t, "M10-HEX", "M10 hex bolts", days=4, price=1000, cost=900,
                            bom=[("WR", "Steel wire rod", Decimal("0.00002"))])  # fmt: skip
    nuts = await f.product(t, "M8-NYL", "M8 nylock nuts", days=2, price=150, cost=100,
                           bom=[("EN8", "EN8 steel", Decimal("0.00001"))])  # fmt: skip
    await f.stock(t, "WR", Decimal("1.0"))  # 50,000 bolts worth
    await f.stock(t, "EN8", Decimal("0.1"), arrival=TODAY + timedelta(days=5))
    maruti = await f.customer(t, "Maruti Suzuki", tier="key")
    tata = await f.customer(t, "Tata Motors", tier="standard")
    return {"bolts": bolts, "nuts": nuts, "maruti": maruti, "tata": tata}


async def _create(client: AsyncClient, h: dict[str, str], d: dict[str, uuid.UUID], **kw: object) -> dict:  # type: ignore[type-arg]
    body = {"customer_id": str(d["maruti"]), "product_id": str(d["bolts"]), "quantity": "1000",
            "unit_price_paise": 1000, "ship_date": str(TODAY + timedelta(days=20))} | {k: str(v) if isinstance(v, uuid.UUID | date) else v for k, v in kw.items()}  # fmt: skip
    r = await client.post("/orders", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def test_working_days_skip_sundays() -> None:
    fri = date(2026, 11, 13)
    assert working_days_between(fri, fri) == 0
    assert working_days_between(fri, fri + timedelta(days=1)) == 1  # Sat
    assert working_days_between(fri, fri + timedelta(days=3)) == 2  # Sat, (Sun), Mon


async def test_create_computes_money_numbers_and_audit(client: AsyncClient, co: Company, data) -> None:  # type: ignore[no-untyped-def]
    h = await headers_for(client, co)
    o = await _create(client, h, data, quantity="1500", unit_price_paise=1250, unit_cost_paise=1000)
    assert o["number"].startswith("ORD-")
    assert o["sales_paise"] == 1_875_000 and o["cost_paise"] == 1_500_000 and o["profit_paise"] == 375_000
    assert o["margin_pct"] == 20.0
    assert o["processing_days"] == 4  # from the product
    assert o["materials_summary"] == "Steel wire rod 0.03 t"
    log = (await client.get("/audit-log", headers=h, params={"entity_type": "order"})).json()
    assert log["items"][0]["summary"] == f"Order {o['number']} created"


async def test_numbers_are_sequential(client: AsyncClient, co: Company, data) -> None:  # type: ignore[no-untyped-def]
    h = await headers_for(client, co)
    a, b = await _create(client, h, data), await _create(client, h, data)
    assert int(b["number"][4:]) == int(a["number"][4:]) + 1


@pytest.mark.parametrize(
    ("override", "status"),
    [({"ship_date": str(TODAY - timedelta(days=1))}, 400), ({"quantity": "0"}, 422), ({"unit_price_paise": -1}, 422),
     ({"product_id": str(uuid.uuid4())}, 400), ({"customer_id": str(uuid.uuid4())}, 400)],
)  # fmt: skip
async def test_create_validation(client: AsyncClient, co: Company, data, override, status) -> None:  # type: ignore[no-untyped-def]
    h = await headers_for(client, co)
    body = {"customer_id": str(data["maruti"]), "product_id": str(data["bolts"]), "quantity": "10",
            "unit_price_paise": 100, "ship_date": str(TODAY + timedelta(days=5))} | override  # fmt: skip
    assert (await client.post("/orders", headers=h, json=body)).status_code == status


async def test_lifecycle_rules(client: AsyncClient, co: Company, data) -> None:  # type: ignore[no-untyped-def]
    h = await headers_for(client, co)
    o = await _create(client, h, data)
    url = f"/orders/{o['id']}"
    assert (await client.patch(url, headers=h, json={"status": "in_production"})).status_code == 400
    assert (await client.patch(url, headers=h, json={"marked_for_planning": True})).status_code == 400
    r = await client.patch(url, headers=h, json={"status": "accepted", "marked_for_planning": True})
    assert r.status_code == 200 and r.json()["marked_for_planning"] is True
    assert (await client.post(f"{url}/cancel", headers=h, json={"reason": ""})).status_code == 422
    r = await client.post(f"{url}/cancel", headers=h, json={"reason": "Customer withdrew"})
    assert r.json()["status"] == "cancelled" and r.json()["marked_for_planning"] is False
    assert (
        await client.patch(url, headers=h, json={"quantity": "5"})
    ).status_code == 400  # past orders locked


async def test_cannot_cancel_in_production(client: AsyncClient, co: Company, data) -> None:  # type: ignore[no-untyped-def]
    h = await headers_for(client, co)
    o = await _create(client, h, data, status="accepted")
    url = f"/orders/{o['id']}"
    for s in ("planned", "in_production"):
        assert (await client.patch(url, headers=h, json={"status": s})).status_code == 200
    assert (await client.post(f"{url}/cancel", headers=h, json={"reason": "late"})).status_code == 400


async def test_bulk_planning_selection(client: AsyncClient, co: Company, data) -> None:  # type: ignore[no-untyped-def]
    h = await headers_for(client, co)
    a = await _create(client, h, data, status="accepted")
    b = await _create(client, h, data)  # new: sending it to Planning accepts it
    c = await _create(client, h, data, status="accepted")
    await client.patch(f"/orders/{c['id']}", headers=h, json={"status": "planned"})
    r = await client.post(
        "/orders/planning-selection", headers=h, json={"order_ids": [a["id"], c["id"]], "marked": True}
    )
    assert r.status_code == 400 and r.json()["error"]["details"]["orders"] == [c["number"]]
    r = await client.post(
        "/orders/planning-selection", headers=h, json={"order_ids": [a["id"], b["id"]], "marked": True}
    )
    assert r.json()["updated"] == 2 and r.json()["plan"]["stage"] in ("draft", "awaiting")
    assert (await client.get(f"/orders/{b['id']}", headers=h)).json()["status"] == "accepted"
    page = (await client.get("/orders", headers=h, params={"planning_only": True})).json()
    assert sorted(o["number"] for o in page["items"]) == sorted([a["number"], b["number"]])


async def test_permissions(client: AsyncClient, co: Company, data) -> None:  # type: ignore[no-untyped-def]
    h = await headers_for(client, co, "purchaser")
    assert (await client.get("/orders", headers=h)).status_code == 200
    body = {"customer_id": str(data["maruti"]), "product_id": str(data["bolts"]), "quantity": "1",
            "unit_price_paise": 1, "ship_date": str(TODAY + timedelta(days=3))}  # fmt: skip
    assert (await client.post("/orders", headers=h, json=body)).status_code == 403
    assert (
        await client.put("/orders/ranking-settings", headers=h, json={"mode": "profit"})
    ).status_code == 403


# ---- signals, ranking, kpis, filters: a separate company with a known order book --------


@pytest.fixture(scope="module")
async def book(client_mod: AsyncClient) -> tuple[Company, dict[str, str], dict[str, dict]]:  # type: ignore[type-arg]
    co = await make_company("book")
    t = co.id
    bolts = await f.product(
        t, "B", "M10 hex bolts", days=4, bom=[("WR", "Steel wire rod", Decimal("0.0001"))]
    )
    nuts = await f.product(t, "N", "M8 nylock nuts", days=2, bom=[("EN8", "EN8 steel", Decimal("0.0001"))])
    await f.stock(t, "WR", Decimal("1.0"))  # 10,000 bolts
    await f.stock(t, "EN8", Decimal("0.05"), arrival=TODAY + timedelta(days=4))  # 500 nuts, more coming
    key = await f.customer(t, "Key Cust", tier="key")
    occ = await f.customer(t, "Occasional Cust", tier="occasional")
    h = await headers_for(client_mod, co)

    async def mk(name: str, **kw: object) -> dict:  # type: ignore[type-arg]
        body = {"customer_id": str(kw.pop("c", key)), "product_id": str(kw.pop("p", bolts)), "quantity": "1000",
                "unit_price_paise": 1000, "unit_cost_paise": 900, "ship_date": str(TODAY + timedelta(days=20)),
                "priority": "medium"} | {k: str(v) if isinstance(v, date) else v for k, v in kw.items()}  # fmt: skip
        r = await client_mod.post("/orders", headers=h, json=body)
        assert r.status_code == 201, r.text
        return r.json()

    o: dict[str, dict] = {}  # type: ignore[type-arg]
    # Ships first, takes 6,000 bolts of stock (0.6 t) -> fine.
    o["early"] = await mk("early", quantity="6000", ship_date=TODAY + timedelta(days=10), priority="high")
    # Ships later, needs 0.6 t but only 0.4 t left -> short 0.2 t (no arrival) -> Raise PO.
    o["short"] = await mk("short", quantity="6000", ship_date=TODAY + timedelta(days=15),
                          unit_price_paise=5000, unit_cost_paise=1000)  # fmt: skip
    # Nuts: needs 0.1 t, 0.05 on hand, arrival scheduled -> waiting.
    o["waiting"] = await mk(
        "waiting", p=nuts, quantity="1000", ship_date=TODAY + timedelta(days=25), c=occ, priority="low"
    )
    # 4 days of work, ships in 2 working days -> behind by 2. No BOM pressure (nuts are short though).
    o["behind"] = await mk("behind", quantity="10", ship_date=TODAY + timedelta(days=3), priority="high")
    # In production at 50%: 2 days left, ships in 6 working days.
    ip = await mk("ip", quantity="10", ship_date=TODAY + timedelta(days=7), status="accepted")
    for s in ("planned", "in_production"):
        await client_mod.patch(f"/orders/{ip['id']}", headers=h, json={"status": s})
    o["ip"] = (await client_mod.patch(f"/orders/{ip['id']}", headers=h, json={"progress_pct": 50})).json()
    done = await mk("done", quantity="10", status="accepted")
    for s in ("planned", "in_production", "completed", "shipped"):
        await client_mod.patch(f"/orders/{done['id']}", headers=h, json={"status": s})
    o["done"] = done
    return co, h, o


@pytest.fixture(scope="module")
async def client_mod(app, tenants):  # type: ignore[no-untyped-def]
    from httpx import ASGITransport

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test/api") as c:
        yield c


async def _get(client: AsyncClient, h: dict[str, str], oid: str) -> dict:  # type: ignore[type-arg]
    return (await client.get(f"/orders/{oid}", headers=h)).json()


async def test_signals(client_mod: AsyncClient, book) -> None:  # type: ignore[no-untyped-def]
    _, h, o = book
    early = await _get(client_mod, h, o["early"]["id"])
    assert early["signal"]["kind"] == "ready" and early["signal"]["tone"] == "ok"
    short = await _get(client_mod, h, o["short"]["id"])
    assert short["signal"] == {"kind": "material_short", "tone": "md", "label": "Material short",
                               "text": "Steel wire rod short · 0.201 t",  # "behind" ships first and uses 0.001 t
                               "action": {"label": "Raise PO", "href": "/purchasing?material=WR"}}  # fmt: skip
    waiting = await _get(client_mod, h, o["waiting"]["id"])
    assert waiting["signal"]["kind"] == "waiting" and waiting["signal"]["label"] == "Waiting on steel"
    assert waiting["signal"]["text"] == "EN8 steel arriving 17 Nov · 0.05 t short"
    behind = await _get(client_mod, h, o["behind"]["id"])
    assert behind["signal"]["kind"] == "behind" and behind["signal"]["text"].startswith("2 days behind")
    ip = await _get(client_mod, h, o["ip"]["id"])
    assert ip["signal"]["label"] == "Production · 50%"
    assert (await _get(client_mod, h, o["done"]["id"]))["signal"]["label"] == "Shipped"


async def test_kpis(client_mod: AsyncClient, book) -> None:  # type: ignore[no-untyped-def]
    _, h, _ = book
    k = (await client_mod.get("/orders/kpis", headers=h)).json()
    assert k == {"open_orders": 5, "high_priority": 2, "in_production": 1, "ship_in_7_days": 2}


async def test_ranking_modes(client_mod: AsyncClient, book) -> None:  # type: ignore[no-untyped-def]
    _, h, o = book

    async def top(mode: str) -> list[str]:
        r = await client_mod.put("/orders/ranking-settings", headers=h, json={"mode": mode})
        assert r.status_code == 200
        return [x["number"] for x in (await client_mod.get("/orders/top", headers=h)).json()]

    assert (await top("profit"))[0] == o["short"]["number"]  # highest profit
    assert (await top("deadline"))[0] == o["behind"]["number"]  # ships soonest
    assert (await top("requirement"))[:2] == sorted([o["early"]["number"], o["short"]["number"]])
    assert o["waiting"]["number"] not in await top("customer")  # occasional customer ranks last
    assert len(await top("weighted")) == 3
    bad = await client_mod.put("/orders/ranking-settings", headers=h, json={"mode": "weighted", "weights": {
        "requirement": 0, "customer": 0, "profit": 0, "deadline": 0, "priority": 0}})  # fmt: skip
    assert bad.status_code == 422


async def test_list_filters_sort_paging(client_mod: AsyncClient, book) -> None:  # type: ignore[no-untyped-def]
    _, h, o = book

    async def numbers(**params: object) -> list[str]:
        r = await client_mod.get("/orders", headers=h, params=params)
        assert r.status_code == 200, r.text
        return [x["number"] for x in r.json()["items"]]

    assert await numbers(scope="past") == [o["done"]["number"]]
    assert len(await numbers()) == 5
    assert await numbers(status="material_short") == [o["short"]["number"]]
    assert set(await numbers(status="in_production")) == {o["ip"]["number"]}
    assert set(await numbers(priority="high")) == {o["early"]["number"], o["behind"]["number"]}
    assert await numbers(q="nylock") == [o["waiting"]["number"]]
    assert await numbers(customer_id=str(o["waiting"]["customer_id"])) == [o["waiting"]["number"]]
    assert set(await numbers(max_processing_days=2)) == {o["waiting"]["number"]}
    assert (await numbers(sort="sales", desc=True))[0] == o["short"]["number"]
    page = (await client_mod.get("/orders", headers=h, params={"limit": 2, "offset": 2})).json()
    assert page["total"] == 5 and len(page["items"]) == 2
    assert await numbers(ship_from=str(TODAY), ship_to=str(TODAY + timedelta(days=7))) == [
        o["behind"]["number"], o["ip"]["number"]]  # fmt: skip


async def test_orders_are_isolated_between_companies(client_mod: AsyncClient, book) -> None:  # type: ignore[no-untyped-def]
    _, _, o = book
    other = await make_company("other")
    h2 = await headers_for(client_mod, other)
    assert (await client_mod.get("/orders", headers=h2, params={"scope": "all"})).json()["total"] == 0
    assert (await client_mod.get(f"/orders/{o['early']['id']}", headers=h2)).status_code == 404


async def test_editing_other_fields_keeps_money_figures(client: AsyncClient, co: Company, data) -> None:  # type: ignore[no-untyped-def]
    from sqlalchemy import update

    from app.core.db import tenant_session
    from app.orders.models import Order

    h = await headers_for(client, co)
    o = await _create(client, h, data, quantity="120000", unit_price_paise=15)
    async with tenant_session(co.id) as s:  # an agreed total that isn't exactly qty x unit price
        await s.execute(update(Order).where(Order.id == uuid.UUID(o["id"])).values(sales_paise=1_840_000))
    r = await client.patch(
        f"/orders/{o['id']}", headers=h, json={"notes": "Call before dispatch", "priority": "high"}
    )
    assert r.json()["sales_paise"] == 1_840_000
    r = await client.patch(f"/orders/{o['id']}", headers=h, json={"quantity": "100000"})
    assert r.json()["sales_paise"] == 1_500_000  # recalculated once an input changes
