"""Executive Dashboard: owner only, a read-only mirror of the other modules (schedule and machine load from
Planning, delayed orders from Orders, cash flow from Billing, customer health from Customers, alerts that link to
their source record)."""

from datetime import date, timedelta

from httpx import AsyncClient

from tests.conftest import TODAY, headers_for
from tests.test_purchasing import _demo_co

DASH = "/dashboard"


async def test_dashboard_mirrors_the_modules(client: AsyncClient) -> None:
    co = await _demo_co("dash")
    owner = await headers_for(client, co)
    for role in ("planner", "purchaser", "accountant"):  # the owner's view only
        assert (await client.get(DASH, headers=await headers_for(client, co, role))).status_code == 403

    r = await client.get(DASH, headers=owner)
    assert r.status_code == 200, r.text
    d = r.json()
    # default range: this week and next, Monday to Saturday
    monday = TODAY - timedelta(days=TODAY.weekday())
    assert d["range"]["start"] == monday.isoformat()
    assert d["range"]["end"] == (monday + timedelta(days=12)).isoformat()
    assert len(d["range"]["days"]) == 13

    # timeline: no approved plan in the demo -> committed work, the draft's orders are the "new orders"
    t = d["timeline"]
    assert t["source"] == "committed" and t["plan"] is None and t["draft"]["number"].startswith("PLAN-")
    assert t["draft"]["orders"], "the working plan's orders are what After New Orders adds"
    assert t["rows"] and all(r["number"] not in t["draft"]["orders"] for r in t["rows"])
    for m in t["machines"]:
        for day in m["days"]:
            if day["after"] is not None:
                assert day["current"] <= day["after"]
        assert m["over"] == ((m["peak_after"] or 0) > 100)
    added = {o["number"] for m in t["machines"] for o in m["orders"] if o["added"]}
    assert added and added <= set(t["draft"]["orders"])

    # KPIs come from the records
    k = d["kpis"]
    assert k["in_progress"]["note"].endswith("in production")
    assert k["cycle_time"]["note"].startswith("Planned")  # no finished production recorded yet
    assert k["delayed"]["value"] == len(k["delayed_orders"])

    # cash flow: 6 consecutive months ending with the range
    months = [c["month"] for c in d["cash_flow"]]
    assert len(months) == 6 and months[-1] == f"{d['range']['end'][:7]}" and months == sorted(months)

    # customer health = the Customers tab's own counts (FY to date)
    cust = (await client.get("/customers", params={"period": "fytd", "limit": 1}, headers=owner)).json()
    assert d["customers"]["high_value"] == cust["health_counts"]["high_value"]
    assert d["customers"]["repeat"] == cust["health_counts"]["repeat"]
    assert d["customers"]["inactive"] == cust["health_counts"]["inactive"]
    assert d["customers"]["top"]["id"] == cust["items"][0]["id"]

    # every alert points at its source record
    assert all(a["link"].startswith(("/planning", "/orders", "/purchasing", "/billing")) for a in d["alerts"])

    # range rules
    assert (
        await client.get(DASH, params={"from": "2026-11-20", "to": "2026-11-10"}, headers=owner)
    ).status_code == 400
    assert (
        await client.get(DASH, params={"from": "2026-01-01", "to": "2026-12-31"}, headers=owner)
    ).status_code == 400


async def test_delayed_orders_and_actual_cycle_time(client: AsyncClient) -> None:
    co = await _demo_co("dash2")
    owner = await headers_for(client, co)
    orders = (await client.get("/orders", params={"scope": "current", "limit": 100}, headers=owner)).json()[
        "items"
    ]
    acc = [o for o in orders if o["status"] == "accepted" and not o["plan"]]
    late, made = acc[0], acc[1]
    # an open order whose date has passed is delayed, with the reason, and an alert links to it
    r = await client.patch(f"/orders/{late['id']}", json={"ship_date": (TODAY - timedelta(days=3)).isoformat()},
                           headers=owner)  # fmt: skip
    assert r.status_code == 200, r.text
    d = (await client.get(DASH, headers=owner)).json()
    hit = next(o for o in d["kpis"]["delayed_orders"] if o["number"] == late["number"])
    assert "3 days past" in hit["reason"]
    assert any(a["link"] == f"/orders?q={late['number']}" for a in d["alerts"])

    # actual cycle time once an order has gone through production (from the order history)
    for st in ("planned", "in_production", "completed"):
        assert (
            await client.patch(f"/orders/{made['id']}", json={"status": st}, headers=owner)
        ).status_code == 200
    d = (await client.get(DASH, headers=owner)).json()
    assert d["kpis"]["cycle_time"]["note"].startswith("Actual · 1 order")
    assert d["kpis"]["cycle_time"]["value"] is not None and d["kpis"]["cycle_time"]["value"] >= 0
    assert date.fromisoformat(d["range"]["today"]) == TODAY
