"""Planning engine rules (pure, no database)."""

from dataclasses import replace
from datetime import date, timedelta

from app.planning import engine as eng

MON = date(2026, 11, 16)  # a Monday
CNC = eng.Machine("cnc", "CNC 01", "mach", 8, 8, 50_000, 23_000)
PRESS = eng.Machine("press", "Press 01", "mach", 8, 8, 40_000, 20_000)
STEEL = eng.MaterialInfo("steel", "SPS", "Spring steel", "t", 1.0, None, 0, 6_000_000, 620_000, 3)
F = eng.Factory(
    {"cnc": CNC, "press": PRESS}, {"mach": eng.Dept("mach", "Machining", 100, 30_000)}, {"steel": STEEL}
)
R = eng.Rules(penalty_mode="fixed", penalty_value=2_000_000, overhead_pct=0, min_margin_pct=18)


def job(
    i: str, hours: float, deadline: date, machine: str = "cnc", steel: float = 0.0, value: int = 50_000_000
) -> eng.Job:
    return eng.Job(i, f"ORD-{i}", "Cust", "Bolts", 1000, "pcs", value, deadline,
                 steps=(eng.Step(machine, 0, hours),), materials=(("steel", steel),) if steel else ())  # fmt: skip


def run(jobs: list[eng.Job], **kw) -> eng.Eval:  # type: ignore[no-untyped-def]
    inp = eng.Inputs(MON, [j.id for j in jobs], **kw)
    return eng.evaluate(F, R, [], jobs, inp, MON)


def test_finite_capacity_serialises_and_skips_sunday() -> None:
    a, b = job("a", 16, MON + timedelta(2)), job("b", 40, MON + timedelta(6))  # b due Sun -> Sat effectively
    ev = run([a, b])
    rows = ev.a["rows"]
    assert (rows["a"]["start"], rows["a"]["finish"]) == (MON, MON + timedelta(1))
    # b: Wed..Sat = 4 days x 8h = 32h, needs 40h -> Mon (Sunday skipped)
    assert rows["b"]["start"] == MON + timedelta(2)
    assert rows["b"]["finish"] == MON + timedelta(7)
    assert rows["b"]["late_days"] == 1
    assert not [b for b in ev.a["bottlenecks"] if b["kind"] == "machine"]  # never overloads by itself


def test_pinned_finish_forces_overload() -> None:
    a = job("a", 24, MON + timedelta(5))
    ev = run([a], pins={"a": MON + timedelta(1)})
    [b] = [b for b in ev.a["bottlenecks"] if b["kind"] == "machine"]
    assert b["resource"] == "CNC 01" and b["size"] == 8.0


def test_material_short_then_express_fix() -> None:
    a = job("a", 8, MON + timedelta(5), steel=1.5)  # 1 t in stock, 0.5 t short, nothing coming
    ev = run([a])
    [b] = [b for b in ev.a["bottlenecks"] if b["kind"] == "material"]
    assert b["size"] == 0.5
    ev2 = run([a], fixes={"express:steel"})
    assert not [b for b in ev2.a["bottlenecks"] if b["kind"] == "material"]
    assert ev2.fin["fix_cost"] == 620_000


def test_arrival_delays_start_and_express_brings_it_forward() -> None:
    f = replace(
        F, materials={"steel": replace(STEEL, on_hand=0, arrival_date=MON + timedelta(4), arrival_qty=5)}
    )
    a = job("a", 8, MON + timedelta(5), steel=1)
    inp = eng.Inputs(MON, ["a"])
    ev = eng.evaluate(f, R, [], [a], inp, MON)
    assert ev.a["rows"]["a"]["start"] == MON + timedelta(4)
    ev2 = eng.evaluate(f, R, [], [a], replace(inp, fixes={"express:steel"}), MON)
    assert ev2.a["rows"]["a"]["start"] == MON + timedelta(1)


def test_night_shift_fixes_lateness_and_costs_only_hours_used() -> None:
    a = job("a", 24, MON + timedelta(1))  # needs 3 days, due Tue
    ev = run([a])
    assert ev.a["rows"]["a"]["late_days"] == 1
    assert ev.fin["penalty"] == 2_000_000
    fixes = eng.suggest_fixes(F, R, [], [a], eng.Inputs(MON, ["a"]), ev, MON)
    [fx] = fixes
    ev2 = run([a], fixes={fx["id"]})
    assert ev2.a["rows"]["a"]["late_days"] == 0
    assert ev2.fin["fix_cost"] == 8 * 23_000  # 8 extra hours at the night rate
    assert fx["penalty_avoided"] == 2_000_000


def test_percent_penalty() -> None:
    r = eng.Rules(penalty_mode="percent", penalty_value=0.5)
    assert eng.penalty(r, job("a", 1, MON), 2) == 500_000  # 0.5% x 2 days of 5 L


def test_hint_suggests_a_better_order() -> None:
    long_late = job("x", 32, MON + timedelta(10))
    urgent = job("y", 8, MON + timedelta(1))
    inp = eng.Inputs(MON, ["x", "y"])
    cur = eng.evaluate(F, R, [], [long_late, urgent], inp, MON)
    assert cur.late == 1
    hint = eng.suggest_hint(F, R, [], [long_late, urgent], inp, cur, MON)
    assert hint and hint["sequence"] == ["y", "x"] and hint["title"] == "Run ORD-y before ORD-x"


def test_running_orders_come_first_and_options_fill_idle_machines() -> None:
    running = replace(job("r", 16, MON + timedelta(3)), running=True, progress=50)  # 8h left on CNC
    mine = job("m", 8, MON + timedelta(5))
    press_job = job("p", 8, MON + timedelta(5), machine="press", value=40_000_000)
    ev = eng.evaluate(F, R, [running], [mine], eng.Inputs(MON, ["m"]), MON)
    assert ev.a["rows"]["m"]["start"] == MON + timedelta(1)  # CNC busy with the running order on Monday
    opts = eng.options(F, R, [running], [mine, press_job], ["m"], eng.Inputs(MON, ["m"]), MON)
    assert opts["own"]["orders"] == ["m"]
    assert set(opts["part"]["orders"]) == {"m", "p"}  # keeps mine, adds the job for the idle press
    assert opts["part"]["idle_days"] < opts["own"]["idle_days"]


def test_changed_tabs_and_reorder_warning() -> None:
    a, b = job("a", 16, MON + timedelta(1)), job("b", 8, MON + timedelta(5))
    base = eng.compute(F, R, [], [a, b], ["a", "b"], "custom", eng.Inputs(MON, ["a", "b"]), MON, set())
    moved = eng.compute(F, R, [], [a, b], ["a", "b"], "custom", eng.Inputs(MON, ["b", "a"]), MON, set())
    assert 2 in eng.changed_tabs(base, moved) and 3 in eng.changed_tabs(base, moved)
    diff = eng.bottleneck_diff(base, moved)
    assert diff["warn"] and diff["deliveries"][0]["id"] == "a"
