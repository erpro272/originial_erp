"""Finite-capacity scheduling, costing, KPIs and the three selection options (pure engine)."""

from dataclasses import replace
from datetime import date, timedelta

from app.planning import engine as eng

MON = date(2026, 11, 16)  # a Monday; the Sunday before is 15 Nov
DEPT = eng.Dept("d", "Shop", 100, 20_000)  # ₹200 / labour hour
A = eng.Machine("a", "Press 01", "d", 8, 8, 50_000, 0, operators=2)  # ₹500 / machine hour
B = eng.Machine("b", "CNC 01", "d", 8, 8, 60_000, 0)
C = eng.Machine("c", "CNC 02", "d", 8, 8, 40_000, 0)
Q = eng.Machine("q", "QC", "d", 8, 8, 10_000, 0, inspection=True)
STEEL = eng.MaterialInfo("s", "SPS", "Steel", "t", 1.0, None, 0, 10_000_000, 500_000, 2)  # ₹1 L / t
F = eng.Factory({"a": A, "b": B, "c": C, "q": Q}, {"d": DEPT}, {"s": STEEL})
R = eng.Rules(overhead_pct=10, packaging_per_unit=100, min_margin_pct=18)


def op(machine: str, setup: float, qty: float, minutes: float) -> eng.Step:
    """One route operation: hours = setup + qty x minutes / 60 (as the service builds it)."""
    return eng.Step(machine, setup, qty * minutes / 60)


def job(i: str, steps: tuple[eng.Step, ...], due: date, *, qty: float = 1200, steel: float = 0.0,
        value: int = 1_00_00_000, running: bool = False, progress: int = 0) -> eng.Job:  # fmt: skip
    return eng.Job(i, f"ORD-{i}", "Cust", "Bolts", qty, "pcs", value, due, steps=steps,
                   materials=(("s", steel),) if steel else (), running=running, progress=progress)  # fmt: skip


def run(jobs: list[eng.Job], running: list[eng.Job] | None = None, f: eng.Factory = F) -> eng.Eval:
    return eng.evaluate(f, R, running or [], jobs, eng.Inputs(MON, [j.id for j in jobs]), MON)


def test_operation_hours_span_days_and_skip_sunday() -> None:
    # 2 h setup + 1200 x 1 min = 22 h on an 8 h/day machine -> Mon 8, Tue 8, Wed 6
    ev = run([job("x", (op("a", 2, 1200, 1),), MON + timedelta(9))])
    p = ev.sched.placed["x"]
    assert p.steps[0] == {MON: 8.0, MON + timedelta(1): 8.0, MON + timedelta(2): 6.0}
    # starting on a Saturday: no hours on Sunday
    sat = MON + timedelta(5)
    ev2 = eng.evaluate(F, R, [], [job("y", (op("a", 0, 960, 1),), sat + timedelta(9))],
                       eng.Inputs(sat, ["y"]), sat)  # fmt: skip
    assert sorted(ev2.sched.placed["y"].steps[0]) == [sat, sat + timedelta(2)]


def test_route_steps_run_in_order_with_time_of_day_handoff() -> None:
    # step 1: 6 h on Press 01 (Mon 0-6 h); step 2: 4 h on CNC 01 can only use Mon 6-8 h, then Tue
    ev = run([job("x", (op("a", 0, 360, 1), op("b", 0, 240, 1)), MON + timedelta(9))])
    s1, s2 = ev.sched.placed["x"].steps
    assert s1 == {MON: 6.0}
    assert s2 == {MON: 2.0, MON + timedelta(1): 2.0}


def test_running_orders_take_capacity_first_and_parallel_machines_start_day_one() -> None:
    running = job("r", (op("a", 0, 1200, 1),), MON + timedelta(5), running=True, progress=50)  # 10 h left
    on_press = job("p", (op("a", 0, 120, 1),), MON + timedelta(9))
    on_cnc = job("c", (op("c", 0, 600, 1),), MON + timedelta(9))  # 10 h: Mon-Tue
    ev = run([on_press, on_cnc], [running])
    assert ev.sched.placed["r"].steps[0] == {MON: 8.0, MON + timedelta(1): 2.0}
    assert ev.a["rows"]["p"]["start"] == MON + timedelta(1)  # Press 01 is full on Monday
    assert ev.a["rows"]["c"]["start"] == MON  # CNC 02 is free: runs in parallel on day 1
    assert ev.a["groups"][0]["orders"] == ["p", "c"]  # overlapping days = a parallel run


def test_finite_capacity_never_overloads_and_makes_orders_wait() -> None:
    a = job("a", (op("b", 0, 960, 1),), MON + timedelta(1))  # 16 h
    b = job("b", (op("b", 0, 480, 1),), MON + timedelta(2))  # 8 h, queued behind a
    ev = run([a, b])
    assert all(h <= 8.0 + 1e-6 for (m, _), h in ev.sched.used.items() if m == "b")
    assert ev.a["rows"]["b"]["start"] == MON + timedelta(2)
    assert not [x for x in ev.a["bottlenecks"] if x["kind"] == "machine"]


def test_material_shortage_when_cumulative_demand_exceeds_stock() -> None:
    a = job("a", (op("a", 0, 60, 1),), MON + timedelta(5), steel=0.7)
    b = job("b", (op("c", 0, 60, 1),), MON + timedelta(5), steel=0.7)  # 1.4 t needed, 1.0 t in stock
    ev = run([a, b])
    [short] = [x for x in ev.a["bottlenecks"] if x["kind"] == "material"]
    assert round(short["size"], 3) == 0.4 and short["orders"] == ["b"]
    assert not [x for x in run([a]).a["bottlenecks"] if x["kind"] == "material"]


def test_costs_bom_machine_labour_overhead_packaging() -> None:
    j = job("x", (op("a", 2, 600, 1),), MON + timedelta(9), qty=1000, steel=0.5)  # 12 h on Press 01
    c = eng.job_cost(F, R, j)
    assert c["materials"] == 0.5 * 10_000_000
    assert c["machine"] == 12 * 50_000
    assert c["labour"] == 12 * 2 * 20_000  # 2 operators at ₹200
    assert c["overheads"] == round((c["materials"] + c["machine"] + c["labour"]) * 0.10)
    assert c["packaging"] == 1000 * 100
    ev = run([j])
    assert ev.fin["contribution"] == j.value - c["total"]
    assert ev.fin["margin"] == round(100 * (j.value - c["total"]) / j.value, 1)


def test_kpis_window_alongside_idle_and_utilisation() -> None:
    running = job("r", (op("a", 0, 1440, 1),), MON + timedelta(5), running=True)  # Press 01 Mon-Wed
    x = job("x", (op("b", 0, 480, 1),), MON + timedelta(9))  # CNC 01 Mon
    y = job("y", (op("b", 0, 480, 1),), MON + timedelta(9))  # CNC 01 Tue
    ev = run([x, y], [running])
    assert (ev.a["start"], ev.a["end"], ev.a["days"]) == (MON, MON + timedelta(1), 2)  # calendar days
    m = eng.options(F, R, [running], [x, y], ["x", "y"], eng.Inputs(MON, ["x", "y"]), MON)["own"]
    assert m["alongside"] == 2  # both start while the running order is on the floor (Mon-Wed)
    # idle during Mon-Wed: CNC 02 all 3 days, CNC 01 on Wed; QC (inspection) is not counted
    assert m["idle_days"] == 4 and m["idle_machines"] == ["CNC 01", "CNC 02"]
    # utilisation: (24 h running + 16 h planned) / (4 machines x 8 h x 2 days)
    assert m["utilisation"] == round(100 * (16 + 16) / 64)
    assert m["per_day"] == round(m["contribution"] / 2)


def test_three_options_are_distinct() -> None:
    """own = ticked orders as given; part keeps them, fixes avoidable lateness and adds a filler;
    full drops the order that is short of material and picks the clean, best plan."""
    long_ = job("long", (op("b", 0, 1440, 1),), MON + timedelta(9), value=2_00_00_000)  # CNC 01, 3 days
    urgent = job("urgent", (op("b", 0, 480, 1),), MON + timedelta(1))  # CNC 01, due Tue
    short = job("short", (op("a", 0, 240, 1),), MON + timedelta(9), steel=3.0)  # only 1 t steel
    filler = job("fill", (op("c", 0, 480, 1),), MON + timedelta(9))  # idle CNC 02
    cands = [long_, urgent, short, filler]
    picked = ["long", "urgent", "short"]
    inp = eng.Inputs(MON, picked)  # the owner's order: long first -> urgent ships late
    on_floor = [job("run", (op("a", 0, 480, 1),), MON + timedelta(3), running=True)]  # Press 01, Monday
    o = eng.options(F, R, on_floor, cands, picked, inp, MON)
    own, part, full = o["own"], o["part"], o["full"]
    assert set(own["orders"]) == set(picked) and own["late"] == ["urgent"] and own["bottlenecks"] == 2
    assert own["bottleneck_names"] == ["CNC 01", "Steel"]  # CNC 01 competition + the steel shortage
    assert set(picked) <= set(part["orders"]) and "fill" in part["orders"] and part["late"] == []
    assert part["rows"]["fill"]["idle_fill"]  # CNC 02 sat idle while the running order ran
    assert "short" not in full["orders"] and full["late"] == [] and full["bottlenecks"] == 0
    assert "short of steel" in full["dropped"]["short"]
    assert o["best"] == "full"
    assert len({tuple(sorted(x["orders"])) for x in (own, part, full)}) == 3
    # the user's own pick changes the result
    o1 = eng.options(F, R, [], cands, ["fill"], eng.Inputs(MON, ["fill"]), MON)
    assert o1["own"]["orders"] == ["fill"] and o1["own"]["late"] == []


def test_fully_optimized_is_exhaustive_not_greedy() -> None:
    """Two small orders together beat the single most valuable one per production day."""
    big = job("big", (op("a", 0, 2400, 1),), MON + timedelta(9), value=3_00_00_000)  # 5 days on Press 01
    s1 = job("s1", (op("b", 0, 480, 1),), MON + timedelta(9), value=1_20_00_000)  # 1 day on CNC 01
    s2 = job("s2", (op("c", 0, 480, 1),), MON + timedelta(9), value=1_20_00_000)  # 1 day on CNC 02
    o = eng.options(F, replace(R, criteria=("late", "per_day")), [], [big, s1, s2], ["big"],
                    eng.Inputs(MON, ["big"]), MON)  # fmt: skip
    assert set(o["full"]["orders"]) == {"big", "s1", "s2"}  # all three run in parallel inside 5 days
