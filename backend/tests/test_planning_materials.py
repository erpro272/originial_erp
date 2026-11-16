"""Material readiness: actual stock and deliveries on order vs the plan's fixes (simulated) vs purchase records.

The checklist and the approval popup both read the same check (`approval.checks[2]`, its `items`)."""

from datetime import date, timedelta

from app.planning import engine as eng
from tests.test_planning_scheduler import DEPT, MON, A, B, R, job, op

TUE, WED, THU = MON + timedelta(1), MON + timedelta(2), MON + timedelta(3)


def factory(on_hand: float, arrival: date | None = None, arriving: float = 0.0) -> eng.Factory:
    steel = eng.MaterialInfo("s", "WR8", "Steel wire rod", "t", on_hand, arrival, arriving, 10_000_000,
                             620_000, 3, "Shree Steels")  # fmt: skip
    return eng.Factory({"a": A, "b": B}, {"d": DEPT}, {"s": steel})


def plan(f: eng.Factory, fixes: set[str] | None = None, requested: dict | None = None) -> dict:  # type: ignore[type-arg]
    j = job("x", (op("a", 0, 240, 1),), MON + timedelta(9), steel=3.0, qty=1000)  # needs 3 t
    inp = eng.Inputs(MON, ["x"], fixes=fixes or set())
    return eng.compute(f, R, [], [j], ["x"], "custom", inp, MON, requested or {})


def material_check(out: dict) -> dict:  # type: ignore[type-arg]
    return next(
        c
        for c in out["approval"]["checks"]
        if c["title"].startswith(("Material", "All materials", "1 material"))
    )


def test_enough_stock_means_no_purchase_need_and_no_warning() -> None:
    out = plan(factory(on_hand=5.0))
    assert out["purchase_needs"] == []
    c = material_check(out)
    assert c["ok"] and c["title"] == "All materials in stock" and c["items"] == []


def test_short_without_fix_needs_a_po_and_stays_a_bottleneck() -> None:
    out = plan(factory(on_hand=0.6))
    [n] = out["purchase_needs"]
    assert (n["action"], n["qty"], n["arrives"], n["requested"]) == ("po", 2.4, None, False)
    c = material_check(out)
    assert not c["ok"] and c["title"] == "1 material PO not raised yet" and c["action"] == "raise_po"
    assert c["items"][0]["text"].startswith(
        "PO for 2.4 t Steel wire rod not raised yet · not in stock and nothing on order"
    )
    assert any(b["kind"] == "material" for b in out["schedule"]["bottlenecks"])


def test_express_fix_is_a_plan_assumption_with_a_real_delivery_time() -> None:
    """The fix doesn't add stock: it assumes an express PO, which arrives 3 days after ordering."""
    out = plan(factory(on_hand=0.6), fixes={"express:s"})
    [n] = out["purchase_needs"]
    assert n["action"] == "express_po" and not n["requested"] and n["request"] is None
    assert n["arrives"] == THU.isoformat()  # ordered today (Mon) + 3 days
    # the order can't start before the express steel is there (no longer scheduled as if it were on the floor)
    assert out["sequence"]["rows"][0]["start"] == THU.isoformat()
    assert not any(
        b["kind"] == "material" for b in out["schedule"]["bottlenecks"]
    )  # planned for: no bottleneck
    c = material_check(out)
    assert not c["ok"] and c["title"] == "1 material PO not raised yet"
    assert c["items"][0] == {
        "material": "s",
        "open": True,
        "text": "Express PO for 2.4 t Steel wire rod from Shree Steels not raised yet · planned fix, not ordered: "
        "arrives 19 Nov if ordered today · needed 19 Nov for ORD-x",
    }


def test_raised_po_shows_its_status_and_expected_arrival() -> None:
    """A purchase request exists (actual record): the check is ready, and says it's not received yet."""
    req = {
        "s": {"status": "requested", "at": MON - timedelta(2), "express": True, "qty": 2.4}
    }  # asked on Saturday
    out = plan(factory(on_hand=0.6), fixes={"express:s"}, requested=req)
    [n] = out["purchase_needs"]
    assert n["requested"] and n["request"]["status"] == "requested"
    assert n["arrives"] == TUE.isoformat()  # Sat + 3 days = Tue: arrives from the actual order day
    assert out["sequence"]["rows"][0]["start"] == TUE.isoformat()
    c = material_check(out)
    assert c["ok"] and c["title"] == "Material POs raised · not received yet" and c["action"] is None
    assert c["items"][0]["text"] == (
        "Express PO for 2.4 t Steel wire rod requested 14 Nov · waiting for Purchasing to raise the PO · "
        "expected 17 Nov · needed 17 Nov for ORD-x"
    )


def test_material_already_on_order_needs_no_po() -> None:
    """Covered by a delivery on order: the order waits for it; nothing to raise (the old bug asked for a PO)."""
    out = plan(factory(on_hand=0.6, arrival=WED, arriving=5.0))
    [n] = out["purchase_needs"]
    assert n["action"] is None and n["arrives"] == WED.isoformat()
    c = material_check(out)
    assert c["ok"] and c["title"] == "Materials covered by stock and deliveries on order"
    assert (
        c["items"][0]["text"]
        == "2.4 t Steel wire rod already on order, arriving 18 Nov · ORD-x can't start before"
    )
    assert out["sequence"]["rows"][0]["start"] == WED.isoformat()


def test_express_on_an_order_already_placed_is_an_expedite_request() -> None:
    out = plan(factory(on_hand=0.6, arrival=MON + timedelta(5), arriving=5.0), fixes={"express:s"})
    [n] = out["purchase_needs"]
    # on order for Saturday; the fix brings it 3 days forward, to Wednesday
    assert (n["action"], n["on_order"], n["arrives"]) == (
        "expedite",
        (MON + timedelta(5)).isoformat(),
        WED.isoformat(),
    )
    c = material_check(out)
    assert not c["ok"] and "Expedite request from Shree Steels not sent yet" in c["items"][0]["text"]
