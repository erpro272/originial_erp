"""The planning demo scenario, end to end through the API (seeded into a fresh company)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.models import User
from seed import planning_demo
from seed.demo_data import seed_demo
from tests.conftest import AsyncClient, headers_for, make_company


async def _demo(client: AsyncClient, slug: str) -> dict[str, str]:
    co = await make_company(slug)
    eng_ = create_async_engine(get_settings().database_owner_url)
    async with async_sessionmaker(eng_)() as s, s.begin():
        owner = (await s.execute(select(User.id).where(User.email == co.emails["owner"]))).scalar_one()
        await seed_demo(s, co.id, owner)
        await planning_demo.upsert(s, co.id)  # idempotent: running it again changes nothing
    await eng_.dispose()
    return await headers_for(client, co)


async def test_demo_scenario_is_realistic_and_options_are_distinct(client: AsyncClient) -> None:
    h = await _demo(client, "demo-plan")

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


async def test_step2_sequence_on_the_demo(client: AsyncClient) -> None:
    """Proposed manufacturing sequence: generate, feasibility, hint, rules vs locks, options, start date."""
    h = await _demo(client, "demo-seq")
    plan = (await client.get("/planning/plan", headers=h)).json()
    pid, r = plan["id"], plan["result"]
    num = {k: v["number"] for k, v in r["selection"]["orders"].items()}
    by_num = {v: k for k, v in num.items()}
    seq = r["sequence"]
    assert plan["status"] == "draft" and plan["generated_at"] is None and plan["rule"] == "value"
    assert [num[x["id"]] for x in seq["rows"]] == ["ORD-1041", "ORD-1040", "ORD-1044", "ORD-1037"]  # value
    # feasibility: the CNC 01 competition (sized in hours), the steel shortage, the late order
    lines = [(x["tone"], x["text"]) for x in seq["feasibility"]["lines"]]
    assert lines[0][0] == "bad" and lines[0][1].startswith("CNC 01 over capacity by ")
    assert ("bad", "Steel wire rod short by 2.4 t · affects ORD-1041") in lines
    assert lines[-1] == ("warn", "ORD-1044 ships 1 day late")
    ov = seq["overview"]
    assert (ov["orders"], ov["on_time"], ov["late"], ov["bottlenecks"]) == (4, 3, 1, 2)
    # the same two bottlenecks as "Your selection" on step 1
    assert r["selection"]["options"]["own"]["bottlenecks"] == 2
    assert any("CNC 01" in g["conflict"] for g in seq["groups"])
    late_row = next(x for x in seq["rows"] if num[x["id"]] == "ORD-1044")
    assert late_row["warn_machines"] == ["CNC 01"] and late_row["status"] == "late"

    # generate opens the step; recalculate (generate again) refreshes the time
    g = (await client.post(f"/planning/plans/{pid}/generate", headers=h)).json()
    assert g["status"] == "generated" and g["generated_at"]

    # the hint: one move, everything on time; dismiss hides it, apply uses it
    hint = seq["hint"]
    assert hint["title"] == "Run ORD-1044 before ORD-1040" and hint["text"].startswith(
        "All 4 orders ship on time."
    )
    d = (await client.patch(f"/planning/plans/{pid}", json={"dismiss_hint": True}, headers=h)).json()
    assert d["plan"]["result"]["sequence"]["hint"]["dismissed"] is True
    a = (await client.patch(f"/planning/plans/{pid}", json={"apply_hint": True}, headers=h)).json()
    s2 = a["plan"]["result"]["sequence"]
    assert a["plan"]["rule"] == "custom" and s2["overview"]["late"] == 0 and 2 in a["tabs"]
    assert [num[x["id"]] for x in s2["rows"]].index("ORD-1044") < [num[x["id"]] for x in s2["rows"]].index(
        "ORD-1040"
    )

    # lock keeps the slot when the rule changes
    first = s2["rows"][0]["id"]
    await client.patch(f"/planning/plans/{pid}", json={"lock": {first: True}}, headers=h)
    for rule in ("deadline", "margin", "priority", "value"):
        out = (await client.patch(f"/planning/plans/{pid}", json={"rule": rule}, headers=h)).json()
        rows = out["plan"]["result"]["sequence"]["rows"]
        assert rows[0]["id"] == first and rows[0]["locked"]
    # dragging the locked order is refused
    ids = [x["id"] for x in rows]
    bad = await client.patch(f"/planning/plans/{pid}", json={"sequence": ids[1:] + ids[:1]}, headers=h)
    assert bad.status_code == 400 and "Locked" in bad.json()["error"]["message"]
    await client.patch(f"/planning/plans/{pid}", json={"lock": {first: False}}, headers=h)

    # using an optimizer option runs it in the order it was scored in
    opt = r["selection"]["options"]["part"]
    u = (await client.patch(f"/planning/plans/{pid}", json={"use_option": "part"}, headers=h)).json()["plan"]
    assert [x["id"] for x in u["result"]["sequence"]["rows"]] == opt["sequence"] and u["rule"] == "custom"
    assert u["result"]["sequence"]["overview"]["late"] == 0
    assert by_num["ORD-1036"] in [x["id"] for x in u["result"]["sequence"]["rows"]]

    # start date: not in the past
    past = await client.patch(f"/planning/plans/{pid}", json={"start_date": "2020-01-06"}, headers=h)
    assert past.status_code == 400
