"""Supplier scoring rules (pure)."""

from app.purchasing.scoring import Candidate, Weights, pick_top, quality_of, score, stars


def _c(sid: str, rate: int | None, lead: float | None, on_time: float | None, defect: float | None,
       deliveries: int = 5) -> Candidate:  # fmt: skip
    return Candidate(sid, sid.upper(), rate, "quote", lead, "actual", on_time, defect, deliveries)


def test_components_overall_and_badges() -> None:
    jsw = _c("jsw", 68_500_00, 3, 0.97, 0.004)
    tata = _c("tata", 71_000_00, 4, 0.98, 0.001)
    jind = _c("jind", 66_200_00, 6, 0.88, 0.012)
    score([jsw, tata, jind], Weights())
    assert jind.scores["price"] == 1.0 and jsw.scores["lead"] == 1.0
    assert round(jsw.scores["quality"], 2) == 0.96 and quality_of(0.012) == 0.88
    assert jsw.overall is not None and tata.overall is not None and jind.overall is not None
    assert jsw.overall > tata.overall > jind.overall
    assert jind.flags == ["Late risk", "Quality risk"] and jsw.flags == []
    assert jind.note == "Sub-optimal lead times"
    top = pick_top([jsw, tata, jind])
    assert [(b, c.supplier_id) for b, c, _ in top] == [(["Best overall"], "jsw"), (["Highest quality"], "tata"),
                                                       (["Lowest cost"], "jind")]  # fmt: skip
    # one supplier best at everything: one card with every badge, no badge handed to a weaker one
    one = pick_top(score([_c("a", 50_000_00, 2, 1.0, 0.0), _c("b", 60_000_00, 5, 0.8, 0.05)], Weights()))
    assert [(b, c.supplier_id) for b, c, _ in one] == [
        (["Best overall", "Highest quality", "Lowest cost"], "a")
    ]
    assert stars(jsw.overall) >= 4


def test_weights_change_the_winner_and_missing_history_is_not_guessed() -> None:
    cheap_late = _c("a", 60_000_00, 8, 0.80, 0.0)
    pricey_fast = _c("b", 75_000_00, 2, 1.0, 0.0)
    score([cheap_late, pricey_fast], Weights(price=80, on_time=10, quality=5, lead=5))
    assert cheap_late.overall is not None and pricey_fast.overall is not None
    assert cheap_late.overall > pricey_fast.overall
    score([cheap_late, pricey_fast], Weights(price=10, on_time=60, quality=10, lead=20))
    assert pricey_fast.overall > cheap_late.overall  # type: ignore[operator]
    new = _c("n", 70_000_00, 4, None, None, deliveries=0)
    score([new, pricey_fast], Weights())
    assert set(new.scores) == {"price", "lead"} and "No history yet" in new.flags  # rated on what is known
    assert new.note.startswith("No deliveries yet")
    nothing = _c("x", None, None, None, None, deliveries=0)
    score([nothing], Weights())
    assert nothing.overall is None and stars(None) == 0 and pick_top([nothing]) == []
