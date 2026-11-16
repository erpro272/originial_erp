"""Night-shift fixes: an intent for one order, worked out again on every recalculation, judged in the plan."""

from datetime import timedelta

from app.planning import engine as eng
from tests.test_planning_scheduler import DEPT, MON, R, job, op

TUE = MON + timedelta(1)
# CNC 01: 8 h day shift + 8 h night shift at ₹1,000/h night premium
CNC = eng.Machine("b", "CNC 01", "d", 8, 8, 60_000, 100_000)
STEEL = eng.MaterialInfo(
    "s", "WR8", "Steel wire rod", "t", 0.0, None, 0, 1_00_000, 620_000, 3, "Shree Steels"
)
F = eng.Factory({"b": CNC}, {"d": DEPT}, {"s": STEEL})


def jobs(urgent_steel: float = 0.0) -> list[eng.Job]:
    long_ = job("long", (op("b", 0, 2400, 1),), MON + timedelta(20))  # CNC 01, 40 h
    urgent = job("urgent", (op("b", 0, 480, 1),), TUE, steel=urgent_steel)  # CNC 01, 8 h, due Tuesday
    return [long_, urgent]


def plan(fixes: set[str], urgent_steel: float = 0.0) -> dict:  # type: ignore[type-arg]
    js = jobs(urgent_steel)
    return eng.compute(F, R, [], js, ["long", "urgent"], "custom",
                       eng.Inputs(MON, ["long", "urgent"], fixes=set(fixes)), MON, {})  # fmt: skip


def row(out: dict, jid: str) -> dict:  # type: ignore[type-arg]
    return next(r for r in out["sequence"]["rows"] if r["id"] == jid)


def fix(out: dict, fid: str) -> dict:  # type: ignore[type-arg]
    return next(x for x in out["finance"]["fixes"] if x["id"] == fid)


NIGHT = "night:b:for:urgent"


def test_suggested_as_an_intent_for_the_late_order() -> None:
    out = plan(set())
    assert row(out, "urgent")["late_days"] > 0
    s = fix(out, NIGHT)
    assert s["status"] == "resolves" and s["effect"].startswith("Resolves: ORD-urgent on time")
    assert s["penalty_avoided"] == out["finance"]["before"]["penalty"]
    assert s["label"].startswith("Night shift on CNC 01 for ORD-urgent")


def test_chosen_night_shift_puts_the_order_on_time_and_charges_only_its_hours() -> None:
    out = plan({NIGHT})
    # one night shift, as close to the deadline as possible: Tuesday (the deadline)
    assert row(out, "urgent")["late_days"] == 0 and row(out, "urgent")["finish"] == TUE.isoformat()
    s = fix(out, NIGHT)
    assert s["selected"] and s["status"] == "resolves" and s["label"].endswith("· 17 Nov")
    assert s["cost"] == 8 * 100_000  # 8 night hours, used by the urgent order only
    assert out["finance"]["with"]["penalty"] == 0


def test_night_hours_are_kept_for_the_target_order() -> None:
    """An older fixed window lets whoever comes first take the hours: the long order ate them."""
    legacy = plan({f"night:b:{MON.isoformat()}:{(MON + timedelta(4)).isoformat()}"})
    assert row(legacy, "urgent")["late_days"] > 0
    intent = plan({NIGHT})
    assert row(intent, "urgent")["late_days"] == 0


def test_older_window_made_for_one_late_order_is_upgraded_to_its_intent() -> None:
    out = plan({f"night:b:{MON.isoformat()}:{TUE.isoformat()}"})  # ends on urgent's deadline: made for it
    assert out["inputs"]["fixes"] == [NIGHT] and row(out, "urgent")["late_days"] == 0


def test_another_fix_that_delays_the_order_shows_the_night_shift_no_longer_works() -> None:
    """The owner's case: night shift + express steel. The express steel can only arrive Thursday, after the
    Tuesday deadline: the night shift can't save it, and says so; it isn't charged for hours nobody used."""
    out = plan({NIGHT, "express:s"}, urgent_steel=1.0)
    assert row(out, "urgent")["late_days"] > 0  # truthfully still late
    s = fix(out, NIGHT)
    assert s["status"] in ("no_effect", "partly") and "still" in s["effect"]
    assert s["penalty_avoided"] == 0 and s["cost"] == 0
    e = fix(out, "express:s")
    assert e["status"] == "planned" and "PO still has to be raised" in e["effect"]
    late = next(c for c in out["approval"]["checks"] if "late" in c["title"])
    assert not late["ok"]  # the checklist doesn't pretend the fix worked


def test_night_shift_follows_the_order_when_the_sequence_changes() -> None:
    js = jobs()
    out = eng.compute(F, R, [], js, ["long", "urgent"], "custom",
                      eng.Inputs(MON, ["urgent", "long"], fixes={NIGHT}), MON, {})  # fmt: skip
    # urgent first: on time without the shift; the shift is reported as not needed (and costs nothing)
    s = fix(out, NIGHT)
    assert row(out, "urgent")["late_days"] == 0 and s["status"] == "not_needed" and s["cost"] == 0


def test_fewest_night_shifts_closest_to_the_deadline() -> None:
    """A 16 h job due Wednesday behind 40 h of other work: two night shifts (Tue, Wed), not five."""
    long_ = job("long", (op("b", 0, 2400, 1),), MON + timedelta(20))
    big = job("big", (op("b", 0, 960, 1),), MON + timedelta(2))  # 16 h, due Wednesday
    out = eng.compute(F, R, [], [long_, big], ["long", "big"], "custom",
                      eng.Inputs(MON, ["long", "big"], fixes={"night:b:for:big"}), MON, {})  # fmt: skip
    s = fix(out, "night:b:for:big")
    assert row(out, "big")["late_days"] == 0 and s["status"] == "resolves"
    assert s["cost"] == 16 * 100_000 and s["label"].endswith("· 17–18 Nov")
