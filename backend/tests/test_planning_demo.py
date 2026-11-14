"""The planning demo scenario, end to end through the API (seeded into a fresh company)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.models import User
from seed import planning_demo
from seed.demo_data import seed_demo
from tests.conftest import AsyncClient, headers_for, make_company


async def test_demo_scenario_is_realistic_and_options_are_distinct(client: AsyncClient) -> None:
    co = await make_company("demo-plan")
    eng_ = create_async_engine(get_settings().database_owner_url)
    async with async_sessionmaker(eng_)() as s, s.begin():
        owner = (await s.execute(select(User.id).where(User.email == co.emails["owner"]))).scalar_one()
        await seed_demo(s, co.id, owner)
        await planning_demo.upsert(s, co.id)  # idempotent: running it again changes nothing
    await eng_.dispose()
    h = await headers_for(client, co)

    plan = (await client.get("/planning/plan", headers=h)).json()  # orders were sent: a draft starts
    sel = plan["result"]["selection"]
    num = {k: v["number"] for k, v in sel["orders"].items()}
    by_num = {v: k for k, v in num.items()}

    # 7 accepted candidates, 4 ticked; margins computed from costs, all realistic (13-32 %).
    assert len(sel["orders"]) == 7
    assert sorted(num[i] for i in sel["selected"]) == ["ORD-1037", "ORD-1040", "ORD-1041", "ORD-1044"]
    assert all(13 <= o["est_margin"] <= 32 for o in sel["orders"].values())
    assert (
        sel["orders"][by_num["ORD-1035"]]["est_margin"]
        < 18
        <= sel["orders"][by_num["ORD-1036"]]["est_margin"]
    )

    # Running orders hold machines for several days; every bar has a machine and a customer.
    run = sel["running"]
    assert len(run) == 5 and all(r["machine"] and r["customer"] for r in run)
    assert sum(1 for r in run if r["finish"] > r["start"]) >= 4

    o = sel["options"]
    own, part, full = o["own"], o["part"], o["full"]
    # every bar has a route
    assert all(r["route"] for opt in (own, part, full) for r in opt["rows"].values())
    # Your selection: tie rods start day 1 on Assembly 2 next to the running orders; one order 1 day late
    # (CNC 01 contention) and a real steel shortage.
    assert own["rows"][by_num["ORD-1037"]]["route"] == ["Assembly 2"]
    assert own["rows"][by_num["ORD-1037"]]["start"] == min(r["start"] for r in run)
    assert [num[i] for i in own["late"]] == ["ORD-1044"] and own["rows"][by_num["ORD-1044"]]["late_days"] == 1
    assert "Steel wire rod" in own["bottleneck_names"]
    # Partly: keeps all 4, removes the late delivery by re-sequencing, fills idle CNC 02.
    assert set(own["orders"]) <= set(part["orders"]) and part["late"] == []
    assert part["rows"][by_num["ORD-1036"]]["idle_fill"] and part["rows"][by_num["ORD-1036"]]["route"] == [
        "CNC 02"
    ]
    # Fully: clean plan, drops the order short of steel with a reason from the simulation.
    assert full["late"] == [] and full["bottlenecks"] == 0
    assert "short of steel wire rod" in full["dropped"][by_num["ORD-1041"]]
    # The low-margin order waiting for EN8 is in no option (Excluded on screen).
    assert by_num["ORD-1035"] not in part["orders"] + full["orders"]
    assert len({tuple(sorted(x["orders"])) for x in (own, part, full)}) == 3 and o["best"] == "full"

    # Ticking changes the result.
    r = (
        await client.patch(
            f"/planning/plans/{plan['id']}", headers=h, json={"selected": [by_num["ORD-1037"]]}
        )
    ).json()
    assert r["plan"]["result"]["selection"]["options"]["own"]["orders"] == [by_num["ORD-1037"]]
