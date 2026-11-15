"""Step 2 (Proposed manufacturing sequence): rules vs locks, the hint, constraints, feasibility lines."""

from datetime import timedelta

from app.planning import engine as eng
from tests.test_planning_scheduler import MON, F, R, job, op


def test_locked_orders_keep_their_slot_when_the_rule_changes() -> None:
    assert eng.keep_locked(["c", "b", "a"], ["a", "b", "c"], {"a": MON}) == ["a", "c", "b"]
    assert eng.keep_locked(["c", "b", "a"], ["a", "b", "c"], {"b": MON}) == ["c", "b", "a"]
    assert eng.keep_locked(["c", "a"], ["a", "b", "c"], {"c": MON}) == ["a", "c"]  # b removed: slot 2 > len
    a = job("a", (op("b", 0, 60, 1),), MON + timedelta(9), value=1_00_00_000)
    b = job("b", (op("c", 0, 60, 1),), MON + timedelta(9), value=3_00_00_000)
    inp = eng.Inputs(MON, ["a", "b"], locks={"a": MON})
    out = eng.compute(F, R, [], [a, b], ["a", "b"], "value", inp, MON, set())
    assert [r["id"] for r in out["sequence"]["rows"]] == ["a", "b"]  # value would put b first
    out = eng.compute(F, R, [], [a, b], ["a", "b"], "value", eng.Inputs(MON, ["a", "b"]), MON, set())
    assert [r["id"] for r in out["sequence"]["rows"]] == ["b", "a"]


def _competing() -> tuple[list[eng.Job], eng.Inputs]:
    long_ = job("long", (op("b", 0, 1440, 1),), MON + timedelta(9))  # CNC 01, 24 h = Mon-Wed
    urgent = job("urgent", (op("b", 0, 480, 1),), MON + timedelta(1))  # CNC 01, 8 h, due Tue
    return [long_, urgent], eng.Inputs(MON, ["long", "urgent"])


def test_late_order_names_the_machine_and_the_hours_it_is_short() -> None:
    jobs, inp = _competing()
    ev = eng.evaluate(F, R, [], jobs, inp, MON)
    assert ev.a["rows"]["urgent"]["late_days"] == 2  # waits for CNC 01 until Thu
    [c] = eng.constraints(F, R, [], jobs, inp, ev, MON)
    assert (c["resource"], c["size"], c["from"], c["to"]) == ("CNC 01", 8.0, MON, MON + timedelta(2))
    assert c["orders"] == ["urgent"] and c["title"] == "CNC 01 over capacity by 8 hrs"
    lines = eng.feasibility(F, [c, *ev.a["bottlenecks"]], {"long": "ORD-long", "urgent": "ORD-urgent"})
    assert [(x["tone"], x["text"]) for x in lines] == [
        ("bad", "CNC 01 over capacity by 8 hrs, 16–18 Nov"),
        ("warn", "ORD-urgent ships 2 days late"),
    ]
    # on time: nothing to report
    assert eng.constraints(F, R, [], jobs[:1], eng.Inputs(MON, ["long"]), eng.evaluate(
        F, R, [], jobs[:1], eng.Inputs(MON, ["long"]), MON), MON) == []  # fmt: skip


def test_route_step_waits_for_the_previous_step_even_when_forced_by_a_date() -> None:
    # step 2 can only start at 6 h on Monday: forced to finish Monday, 6 of its 8 hours don't fit
    j = job("x", (op("a", 0, 360, 1), op("b", 0, 480, 1)), MON)
    s = eng.schedule(F, [], [j], eng.Inputs(MON, ["x"], pins={"x": MON}), MON)
    assert round(s.overflow["x"], 6) == 6.0


def test_hint_moves_the_urgent_order_first_unless_a_lock_holds_the_slot() -> None:
    jobs, inp = _competing()
    out = eng.compute(F, R, [], jobs, ["long", "urgent"], "custom", inp, MON, set())
    seq = out["sequence"]
    assert seq["hint"]["title"] == "Run ORD-urgent before ORD-long"
    assert seq["hint"]["sequence"] == ["urgent", "long"]
    assert seq["hint"]["text"].startswith("All 2 orders ship on time. ORD-long")
    assert seq["overview"]["late"] == 1 and seq["overview"]["bottlenecks"] == 1
    row_urgent = seq["rows"][1]
    assert row_urgent["warn_machines"] == ["CNC 01"] and row_urgent["status"] == "late"
    locked = eng.compute(F, R, [], jobs, ["long", "urgent"], "custom",
                         eng.Inputs(MON, ["long", "urgent"], locks={"long": MON}), MON, set())  # fmt: skip
    assert locked["sequence"]["hint"] is None  # moving urgent up would move the locked order


def test_parallel_group_names_the_shared_machine_that_causes_the_overload() -> None:
    jobs, inp = _competing()
    other = job("other", (op("c", 0, 480, 1),), MON + timedelta(9))  # CNC 02, Monday: a different line
    out = eng.compute(F, R, [], [*jobs, other], ["other", "long", "urgent"], "custom",
                      eng.Inputs(MON, ["other", "long", "urgent"]), MON, set())  # fmt: skip
    groups = out["sequence"]["groups"]
    assert groups[0]["orders"] == ["other", "long"] and groups[0]["conflict"] == []
    assert groups[1]["orders"] == ["urgent"]
    both = eng.compute(F, R, [], jobs, ["long", "urgent"], "custom", inp, MON, set())["sequence"]["groups"]
    assert both == [
        {"orders": ["long"], "shared": [], "conflict": []},
        {"orders": ["urgent"], "shared": [], "conflict": []},
    ]


def test_schedule_chips_and_the_days_a_late_order_queued() -> None:
    jobs, inp = _competing()
    sch = eng.compute(F, R, [], jobs, ["long", "urgent"], "custom", inp, MON, set())["schedule"]
    assert sch["chips"] == [
        {"kind": "constraint", "tone": "bad", "title": "CNC 01 over capacity",
         "text": "16–18 Nov · +8 hrs · ORD-urgent waits"},
    ]  # fmt: skip
    urgent = next(r for r in sch["rows"] if r["id"] == "urgent")
    assert urgent["wait"] == [
        {"machine": "CNC 01", "from": MON.isoformat(), "to": (MON + timedelta(2)).isoformat()}
    ]
    assert [c["resource"] for c in sch["constraints"]] == ["CNC 01"]


def test_forced_finish_date_overloads_and_the_diff_warns() -> None:
    """Dragging the urgent order's finish to its deadline books CNC 01 over its hours (a real overload)."""
    jobs, inp = _competing()
    before = eng.compute(F, R, [], jobs, ["long", "urgent"], "custom", inp, MON, set())
    pinned = eng.Inputs(MON, ["long", "urgent"], pins={"urgent": MON + timedelta(1)})
    after = eng.compute(F, R, [], jobs, ["long", "urgent"], "custom", pinned, MON, set())
    [over] = after["schedule"]["bottlenecks"]
    assert over["kind"] == "machine" and over["resource"] == "CNC 01" and round(over["size"]) == 8
    load = next(lr for lr in after["schedule"]["load"] if lr["name"] == "CNC 01")
    assert load["over"] and max(v for v in load["days"].values() if v) == 150
    urgent = next(r for r in after["schedule"]["rows"] if r["id"] == "urgent")
    assert urgent["over_days"] and urgent["finish"] == (MON + timedelta(1)).isoformat()
    diff = eng.bottleneck_diff(before, after)
    assert diff["warn"] and [b["kind"] for b in diff["worse"]] == ["machine"]
    assert [b["kind"] for b in diff["better"]] == ["constraint"]  # the queue is gone: it's on time now
    assert diff["deliveries"] == [
        {"id": "urgent", "was": 2, "now": 0, "finish": (MON + timedelta(1)).isoformat()}
    ]
