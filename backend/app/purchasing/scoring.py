"""Supplier scoring: pure functions, no DB.

Per supplier and material: a rate (latest valid quote, else last price paid) and a lead time (average actual
days from PO sent to the gate, else the quoted lead time). Per supplier (all materials): on-time % (deliveries
at the gate on or before the date the supplier committed to) and defect rate (QC rejected / inspected).

Component scores are 0..1 and relative to the other suppliers of the same material where that makes sense:
  price    = cheapest rate / this rate
  lead     = shortest lead time / this lead time
  on_time  = on-time fraction
  quality  = 1 - 10 x defect rate (each 1% rejected costs a tenth), never below 0
Overall = weighted average of the components that are known (the company's weights, re-normalised when a
supplier has no delivery history yet), as a %. Quality score shown out of 10 = 10 x quality.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Weights:
    price: float = 40
    on_time: float = 25
    quality: float = 25
    lead: float = 10
    late_risk_below: float = 90.0  # on-time % below this: "Late risk"
    quality_risk_above: float = 1.0  # defect % above this: "Quality risk"


@dataclass
class Candidate:
    supplier_id: str
    supplier: str
    rate: int | None  # paise per unit
    rate_source: str  # quote | last_po | none
    lead_days: float | None
    lead_source: str  # actual | quote | none
    on_time: float | None  # 0..1, None = no deliveries yet
    defect: float | None  # 0..1, None = nothing inspected yet
    deliveries: int = 0
    scores: dict[str, float] = field(default_factory=dict)
    overall: float | None = None  # %
    flags: list[str] = field(default_factory=list)
    note: str = ""


def quality_of(defect: float | None) -> float | None:
    return None if defect is None else max(0.0, 1.0 - 10.0 * defect)


def score(cands: list[Candidate], w: Weights) -> list[Candidate]:
    """Fill scores, overall %, flags and a one-line note for the suppliers of one material."""
    rates = [c.rate for c in cands if c.rate]
    leads = [c.lead_days for c in cands if c.lead_days]
    best_rate, best_lead = (min(rates) if rates else None), (min(leads) if leads else None)
    weights = {"price": w.price, "on_time": w.on_time, "quality": w.quality, "lead": w.lead}
    for c in cands:
        s: dict[str, float] = {}
        if c.rate and best_rate:
            s["price"] = best_rate / c.rate
        if c.lead_days and best_lead:
            s["lead"] = best_lead / c.lead_days
        if c.on_time is not None:
            s["on_time"] = c.on_time
        q = quality_of(c.defect)
        if q is not None:
            s["quality"] = q
        c.scores = s
        total = sum(weights[k] for k in s)
        c.overall = round(100 * sum(weights[k] * v for k, v in s.items()) / total, 1) if total else None
        c.flags = []
        if c.on_time is not None and 100 * c.on_time < w.late_risk_below:
            c.flags.append("Late risk")
        if c.defect is not None and 100 * c.defect > w.quality_risk_above:
            c.flags.append("Quality risk")
        if not c.deliveries:
            c.flags.append("No history yet")
        c.note = _note(c)
    return cands


def _note(c: Candidate) -> str:
    s = c.scores
    if "No history yet" in c.flags:
        return "No deliveries yet: rated on its quote only"
    weak = min(s, key=lambda k: s[k]) if s else None
    if weak and s[weak] < 0.85:
        return {"price": "Higher rate than others", "lead": "Sub-optimal lead times",
                "on_time": "Often late", "quality": "Quality issues at QC"}[weak]  # fmt: skip
    if s.get("quality", 0) >= 0.97 and s.get("on_time", 0) >= 0.95:
        return "Exceptional quality record"
    if s.get("price", 0) >= 0.95 and s.get("on_time", 0) >= 0.9:
        return "Price & delivery score high"
    return "Reliable all round"


def stars(overall: float | None) -> int:
    return 0 if overall is None else max(1, min(5, round(overall / 20)))


def pick_top(cands: list[Candidate]) -> list[tuple[list[str], Candidate, float]]:
    """Best overall, highest quality and lowest cost, each to its real winner. A supplier that wins more than
    one gets one card with all its badges (never a badge it didn't earn). Returns (badges, supplier, the % on
    the first badge: overall score, or quality for a quality-only card)."""
    rated = [c for c in cands if c.overall is not None]
    if not rated:
        return []
    winners: list[tuple[str, Candidate]] = [
        ("Best overall", max(rated, key=lambda c: (c.overall, c.scores.get("price", 0))))
    ]
    with_q = [c for c in rated if "quality" in c.scores]
    if with_q:
        winners.append(
            ("Highest quality", max(with_q, key=lambda c: (c.scores["quality"], c.scores.get("on_time", 0))))
        )
    with_rate = [c for c in rated if c.rate]
    if with_rate:
        winners.append(("Lowest cost", min(with_rate, key=lambda c: (c.rate, -(c.overall or 0)))))
    cards: dict[str, tuple[list[str], Candidate]] = {}
    for badge, c in winners:
        cards.setdefault(c.supplier_id, ([], c))[0].append(badge)
    out = []
    for badges, c in cards.values():
        pct = round(100 * c.scores["quality"], 1) if badges == ["Highest quality"] else (c.overall or 0.0)
        out.append((badges, c, pct))
    return out
