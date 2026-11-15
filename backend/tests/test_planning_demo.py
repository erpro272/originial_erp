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


async def test_step3_schedule_on_the_demo(client: AsyncClient) -> None:
    """Production schedule: chips, queue days, preview warning, finish-date pins, hard blocks, save."""
    h = await _demo(client, "demo-sch")
    plan = (await client.get("/planning/plan", headers=h)).json()
    pid, r = plan["id"], plan["result"]
    num = {k: v["number"] for k, v in r["selection"]["orders"].items()}
    by_num = {v: k for k, v in num.items()}
    sch = r["schedule"]
    assert [c["title"] for c in sch["chips"]] == ["CNC 01 over capacity", "Steel wire rod short 2.4 t"]
    late = next(x for x in sch["rows"] if x["id"] == by_num["ORD-1044"])
    assert late["wait"][0]["machine"] == "CNC 01"
    assert sum(1 for x in sch["rows"] if x["running"]) == 5
    assert all(st["setup"] == 0 for x in sch["rows"] if x["running"] for st in x["steps"])

    # preview a reorder that makes things worse: nothing is saved
    ids = [x["id"] for x in r["sequence"]["rows"]]
    worse = [by_num["ORD-1044"], *[i for i in ids if i != by_num["ORD-1044"]]][::-1]
    pv = (
        await client.patch(f"/planning/plans/{pid}?preview=true", json={"sequence": worse}, headers=h)
    ).json()
    assert "warn" in pv["diff"]
    again = (await client.get("/planning/plan", headers=h)).json()
    assert [x["id"] for x in again["result"]["sequence"]["rows"]] == ids  # preview saved nothing

    # pin ORD-1044 to its deadline: on time, CNC 01 really overloaded (red), the warning lists it
    dl = r["selection"]["orders"][by_num["ORD-1044"]]["deadline"]
    pv = (await client.patch(f"/planning/plans/{pid}?preview=true", json={"pin": {by_num["ORD-1044"]: dl}},
                             headers=h)).json()  # fmt: skip
    assert pv["diff"]["warn"] and any(b["kind"] == "machine" for b in pv["diff"]["worse"])
    out = (
        await client.patch(f"/planning/plans/{pid}", json={"pin": {by_num["ORD-1044"]: dl}}, headers=h)
    ).json()
    rows = {x["id"]: x for x in out["plan"]["result"]["sequence"]["rows"]}
    assert rows[by_num["ORD-1044"]]["pinned"] == dl and rows[by_num["ORD-1044"]]["late_days"] == 0
    assert any(lr["over"] for lr in out["plan"]["result"]["schedule"]["load"])
    # release the pin
    out = (
        await client.patch(f"/planning/plans/{pid}", json={"pin": {by_num["ORD-1044"]: None}}, headers=h)
    ).json()
    assert out["plan"]["result"]["sequence"]["rows"][2]["pinned"] is None

    # hard blocks: before the plan starts, before the material arrives
    bad = await client.patch(
        f"/planning/plans/{pid}", json={"pin": {by_num["ORD-1044"]: "2020-01-01"}}, headers=h
    )
    assert bad.status_code == 400

    # save schedule: a checkpoint in the history (needs a generated plan)
    assert (await client.post(f"/planning/plans/{pid}/save-schedule", headers=h)).status_code == 400
    await client.post(f"/planning/plans/{pid}/generate", headers=h)
    saved = (await client.post(f"/planning/plans/{pid}/save-schedule", headers=h)).json()
    assert saved["schedule_saved_at"] and saved["last_change"]["summary"] == "Schedule saved"


async def test_step4_finance_and_fixes_on_the_demo(client: AsyncClient) -> None:
    """Financial analysis: before / with fixes, penalty rule, minimum margin, a fix changes the plan."""
    h = await _demo(client, "demo-fin")
    plan = (await client.get("/planning/plan", headers=h)).json()
    pid, r = plan["id"], plan["result"]
    num = {k: v["number"] for k, v in r["selection"]["orders"].items()}
    fin = r["finance"]
    before = fin["before"]
    assert before["min_margin"] == 18 and before["penalty_rule"] == {"mode": "fixed", "value": 2000000}
    assert before["penalty"] == 2000000 and before["fix_cost"] == 0
    late = [x for x in before["rows"] if x["penalty"]]
    assert [(num[x["id"]], x["late_days"]) for x in late] == [("ORD-1044", 1)]
    assert sum(before["breakdown"].values()) == before["mfg_cost"]
    assert before["contribution"] == before["value"] - before["mfg_cost"] - before["penalty"]
    assert fin["with"] == fin["before"]  # nothing ticked yet

    # the night shift on Press 01 pays for the 2.25 h ORD-1044's last step runs past the day shift
    press = next(x for x in fin["fixes"] if x["label"].startswith("Night shift on Press 01"))
    assert press["cost"] == round(2.25 * 115000) and press["penalty_avoided"] == 2000000
    assert press["solves"] == ["ORD-1044 ships 1 day late"]
    out = (await client.patch(f"/planning/plans/{pid}", json={"fixes": [press["id"]]}, headers=h)).json()
    assert out["tabs"] == [2, 3, 4, 5]
    f2 = out["plan"]["result"]["finance"]
    w = f2["with"]
    assert w["penalty"] == 0 and w["fix_cost"] == press["cost"]
    assert w["contribution"] == f2["before"]["contribution"] + 2000000 - press["cost"]
    assert next(x for x in f2["fixes"] if x["id"] == press["id"])["selected"]
    assert out["plan"]["result"]["sequence"]["overview"]["late"] == 0  # step 2 follows
    # untick: back to the plan without fixes
    out = (await client.patch(f"/planning/plans/{pid}", json={"fixes": []}, headers=h)).json()
    assert out["plan"]["result"]["finance"]["with"]["penalty"] == 2000000
