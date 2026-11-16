"""Supplier comparison: rates, lead times, on-time delivery and quality per supplier, quotes, the preferred
supplier per material, and the company's scoring rule. The maths is in `scoring.py` (pure); this module loads
the data:

- deliveries = POs that reached the gate in the last 12 months (first gate entry; a replacement for rejected
  goods isn't a new delivery); on time when the goods were at the gate on or before the PO's `promised_date` (what the supplier committed to); lead time = days from
  the PO being sent (approved) to its first gate entry;
- quality = QC results (`po_events` kind qc): rejected / (accepted + rejected);
- rate = the latest valid quote, else the last price paid; lead time = actual, else quoted.
"""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from statistics import mean
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Material, MaterialStock
from app.core import audit, clock
from app.core.errors import DomainError, NotFound
from app.core.services import kv
from app.planning import service as planning
from app.purchasing import scoring
from app.purchasing.models import (
    OPEN,
    PoEvent,
    PreferredSupplier,
    PurchaseOrder,
    PurchaseOrderLine,
    Supplier,
    SupplierQuote,
)
from app.purchasing.schemas import (
    ComparisonKpis,
    ComparisonOut,
    DeliveryOut,
    MaterialRef,
    PreferredIn,
    QuoteOut,
    QuoteReplyIn,
    QuoteRequestIn,
    ScoringRules,
    SupplierDetail,
    SupplierRow,
    TopCard,
)

RULES_KEY = "supplier-scoring"
HISTORY_DAYS = 365
ACTIVE_DAYS = 180


# ---- company rule -----------------------------------------------------------------------------------


async def get_rules(session: AsyncSession) -> ScoringRules:
    try:
        return ScoringRules.model_validate(await kv.get_setting(session, RULES_KEY))
    except (NotFound, ValueError):
        return ScoringRules()


async def put_rules(session: AsyncSession, actor: uuid.UUID, r: ScoringRules) -> ScoringRules:
    if r.price_weight + r.on_time_weight + r.quality_weight + r.lead_weight <= 0:
        raise DomainError("At least one weight must be above 0.")
    await kv.put_setting(session, actor, RULES_KEY, r.model_dump())
    return r


def _weights(r: ScoringRules) -> scoring.Weights:
    return scoring.Weights(price=r.price_weight, on_time=r.on_time_weight, quality=r.quality_weight,
                           lead=r.lead_weight, late_risk_below=r.late_risk_below,
                           quality_risk_above=r.quality_risk_above)  # fmt: skip


# ---- loading ----------------------------------------------------------------------------------------


class _Data:
    def __init__(self) -> None:
        self.suppliers: dict[uuid.UUID, Supplier] = {}
        self.materials: dict[uuid.UUID, Material] = {}
        self.pos: dict[uuid.UUID, PurchaseOrder] = {}
        self.lines: dict[uuid.UUID, list[PurchaseOrderLine]] = defaultdict(list)  # po id -> lines
        self.gates: list[tuple[PurchaseOrder, datetime]] = []  # every gate entry (last 12 months)
        self.qc: dict[uuid.UUID, list[tuple[Decimal, Decimal]]] = defaultdict(list)  # supplier -> (acc, rej)
        self.quotes: list[SupplierQuote] = []
        self.preferred: dict[uuid.UUID, uuid.UUID] = {}  # material -> supplier


async def _load(session: AsyncSession) -> _Data:
    d = _Data()
    since = datetime.now(UTC) - timedelta(days=HISTORY_DAYS)
    d.suppliers = {s.id: s for s in (await session.execute(select(Supplier))).scalars()}
    d.materials = {
        m.id: m for m in (await session.execute(select(Material).order_by(Material.code))).scalars()
    }
    d.pos = {p.id: p for p in (await session.execute(select(PurchaseOrder))).scalars()}
    for ln in (await session.execute(select(PurchaseOrderLine))).scalars():
        d.lines[ln.po_id].append(ln)
    evs = (await session.execute(
        select(PoEvent).where(PoEvent.kind.in_(("gate_entry", "qc")), PoEvent.created_at >= since)
        .order_by(PoEvent.created_at)
    )).scalars()  # fmt: skip
    for e in evs:
        po = d.pos.get(e.po_id)
        if po is None:
            continue
        if e.kind == "gate_entry":
            d.gates.append((po, e.created_at))
        else:
            acc, rej = (
                Decimal(str((e.data or {}).get("accepted", 0))),
                Decimal(str((e.data or {}).get("rejected", 0))),
            )
            if acc + rej > 0:
                d.qc[po.supplier_id].append((acc, rej))
    d.quotes = list(
        (await session.execute(select(SupplierQuote).order_by(SupplierQuote.created_at))).scalars()
    )
    d.preferred = {p.material_id: p.supplier_id
                   for p in (await session.execute(select(PreferredSupplier))).scalars()}  # fmt: skip
    return d


def _quote_out(d: _Data, q: SupplierQuote) -> QuoteOut:
    m, s = d.materials[q.material_id], d.suppliers[q.supplier_id]
    return QuoteOut(id=q.id, supplier_id=s.id, supplier=s.name, material_id=m.id, material=m.name, code=m.code,
                    unit=m.unit, status=q.status, quantity=q.quantity, rate_paise=q.rate_paise,
                    lead_days=q.lead_days, valid_until=q.valid_until, note=q.note, created_at=q.created_at,
                    replied_at=q.replied_at)  # fmt: skip


# ---- comparison ------------------------------------------------------------------------------------


async def comparison(session: AsyncSession) -> ComparisonOut:
    d = await _load(session)
    rules = await get_rules(session)
    today = clock.today()
    now = datetime.now(UTC)

    # supplier-wide history
    # one delivery per PO: its first arrival at the gate (a replacement for rejected goods isn't a new delivery)
    first_gate: dict[uuid.UUID, datetime] = {}
    for po, at in d.gates:
        first_gate.setdefault(po.id, at)
    on_time: dict[uuid.UUID, list[bool]] = defaultdict(list)
    for po_id, at in first_gate.items():
        po = d.pos[po_id]
        if po.promised_date is not None:
            on_time[po.supplier_id].append(at.date() <= po.promised_date)
    lead_actual: dict[tuple[uuid.UUID, uuid.UUID], list[int]] = defaultdict(list)
    for po_id, at in first_gate.items():
        po = d.pos[po_id]
        if po.approved_at is not None:
            for ln in d.lines[po_id]:
                lead_actual[(po.supplier_id, ln.material_id)].append(
                    max(0, (at.date() - po.approved_at.date()).days)
                )
    defect = {s: (float(sum(r for _, r in v) / sum(a + r for a, r in v))) for s, v in d.qc.items()}
    deliveries = {s: len(v) for s, v in on_time.items()}
    open_pos: dict[uuid.UUID, int] = defaultdict(int)
    for po in d.pos.values():
        if po.status in OPEN:
            open_pos[po.supplier_id] += 1
    recent_po = {po.supplier_id for po in d.pos.values()
                 if po.approved_at and po.approved_at >= now - timedelta(days=ACTIVE_DAYS)}  # fmt: skip
    recent_quote = {q.supplier_id for q in d.quotes if q.created_at >= now - timedelta(days=90)}
    active = {s for s in d.suppliers if open_pos.get(s) or s in recent_po or s in recent_quote}

    # per supplier + material: latest valid quote, else last price paid
    quote: dict[tuple[uuid.UUID, uuid.UUID], SupplierQuote] = {}
    for sq in d.quotes:  # oldest first: later ones win
        if sq.status == "received" and sq.valid_until and sq.valid_until >= today:
            quote[(sq.supplier_id, sq.material_id)] = sq
    last_price: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    for po in sorted(d.pos.values(), key=lambda p: p.created_at):
        if po.status != "cancelled":
            for ln in d.lines[po.id]:
                last_price[(po.supplier_id, ln.material_id)] = ln.price_per_unit_paise
    pairs = sorted(set(quote) | set(last_price) | set(lead_actual),
                   key=lambda k: (d.materials[k[1]].code, d.suppliers[k[0]].name))  # fmt: skip

    w = _weights(rules)
    by_material: dict[uuid.UUID, list[scoring.Candidate]] = defaultdict(list)
    for sid, mid in pairs:
        q = quote.get((sid, mid))
        rate, rsrc = (q.rate_paise, "quote") if q else (last_price.get((sid, mid)), "last_po")
        acts = lead_actual.get((sid, mid))
        lead, lsrc = ((mean(acts), "actual") if acts else
                      (float(q.lead_days), "quote") if q and q.lead_days is not None else (None, "none"))  # fmt: skip
        ot = on_time.get(sid)
        by_material[mid].append(scoring.Candidate(
            supplier_id=str(sid), supplier=d.suppliers[sid].name, rate=rate, rate_source=rsrc if rate else "none",
            lead_days=lead, lead_source=lsrc, on_time=(sum(ot) / len(ot)) if ot else None,
            defect=defect.get(sid), deliveries=deliveries.get(sid, 0)))  # fmt: skip

    rows: list[SupplierRow] = []
    top: dict[str, list[TopCard]] = {}
    row_of: dict[tuple[str, uuid.UUID], SupplierRow] = {}
    for mid, cands in by_material.items():
        scoring.score(cands, w)
        m = d.materials[mid]
        for c in cands:
            sid = uuid.UUID(c.supplier_id)
            qv = quote.get((sid, mid))
            r = SupplierRow(
                supplier_id=sid, supplier=c.supplier, material_id=mid, material=m.name, code=m.code,
                category=m.category, unit=m.unit, rate_paise=c.rate, rate_source=c.rate_source,
                lead_days=round(c.lead_days, 1) if c.lead_days is not None else None,
                lead_source=c.lead_source,
                on_time_pct=round(100 * c.on_time, 1) if c.on_time is not None else None,
                defect_pct=round(100 * c.defect, 2) if c.defect is not None else None,
                quality_score=round(10 * q_, 1) if (q_ := scoring.quality_of(c.defect)) is not None else None,
                deliveries=c.deliveries, active_pos=open_pos.get(sid, 0), overall=c.overall,
                stars=scoring.stars(c.overall, c.flags), flags=c.flags, note=c.note, preferred=d.preferred.get(mid) == sid,
                active=sid in active, quote_valid_until=qv.valid_until if qv else None,
            )  # fmt: skip
            rows.append(r)
            row_of[(c.supplier_id, mid)] = r
        top[str(mid)] = [
            TopCard(badges=b, pct=p, note=scoring.card_note(b, c), row=row_of[(c.supplier_id, mid)])
            for b, c, p in scoring.pick_top(cands)
        ]

    rows.sort(key=lambda r: (r.code, -(r.overall if r.overall is not None else -1), r.supplier))
    # KPIs
    recent = [(d.pos[pid], at) for pid, at in first_gate.items() if at >= now - timedelta(days=ACTIVE_DAYS)]
    ot_recent = [at.date() <= po.promised_date for po, at in recent if po.promised_date is not None]
    leads_recent = [(at.date() - d.pos[pid].approved_at.date()).days for pid, at in first_gate.items()  # type: ignore[union-attr]
                    if at >= now - timedelta(days=ACTIVE_DAYS) and d.pos[pid].approved_at is not None]  # fmt: skip
    kpis = ComparisonKpis(
        active_suppliers=len(active),
        avg_on_time_pct=round(100 * sum(ot_recent) / len(ot_recent), 1) if ot_recent else None,
        avg_lead_days=round(mean(leads_recent), 1) if leads_recent else None,
        saved_30d_paise=_saved(d, now),
    )
    # materials: the ones an order needs now first; the default is the most urgent one that has suppliers
    need: dict[uuid.UUID, date] = {}
    need_qty: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for x in await planning.material_demand(session):
        need[x["material_id"]] = min(need.get(x["material_id"], x["needed_by"]), x["needed_by"])
        need_qty[x["material_id"]] += x["qty"]
    on_hand = {st.material_id: st.on_hand for st in (await session.execute(select(MaterialStock))).scalars()}
    mats = [
        MaterialRef(id=m.id, code=m.code, name=m.name, unit=m.unit, needed=m.id in need)
        for m in d.materials.values()
    ]
    with_suppliers = [mid for mid in by_material if top.get(str(mid))]
    # short first (orders need more than is in stock), then the earliest need, then the most suppliers
    urgent = sorted((mid for mid in with_suppliers if mid in need),
                    key=lambda mid: (need_qty[mid] <= on_hand.get(mid, Decimal(0)), need[mid], -len(by_material[mid])))  # fmt: skip
    default = (
        urgent[0]
        if urgent
        else (max(with_suppliers, key=lambda mid: len(by_material[mid])) if with_suppliers else None)
    )
    quotes = [_quote_out(d, q) for q in reversed(d.quotes)
              if q.status == "requested" or q.created_at >= now - timedelta(days=90)]  # fmt: skip
    return ComparisonOut(kpis=kpis, materials=mats, default_material_id=default, top=top, rows=rows, quotes=quotes,
                         rules=rules, today=today)  # fmt: skip


def _saved(d: _Data, now: datetime) -> int:
    """POs approved in the last 30 days, against the material's average rate over the last 90 days
    (all suppliers' received quotes and prices paid): (average - paid) x quantity."""
    seen: dict[uuid.UUID, list[int]] = defaultdict(list)
    for q in d.quotes:
        if q.status == "received" and q.rate_paise and q.created_at >= now - timedelta(days=90):
            seen[q.material_id].append(q.rate_paise)
    for po in d.pos.values():
        if po.approved_at and po.approved_at >= now - timedelta(days=90) and po.status != "cancelled":
            for ln in d.lines[po.id]:
                seen[ln.material_id].append(ln.price_per_unit_paise)
    total = Decimal(0)
    for po in d.pos.values():
        if po.approved_at and po.approved_at >= now - timedelta(days=30) and po.status != "cancelled":
            for ln in d.lines[po.id]:
                rates = seen.get(ln.material_id)
                if rates:
                    total += (Decimal(mean(rates)) - ln.price_per_unit_paise) * ln.quantity
    return int(total)


async def supplier_detail(session: AsyncSession, supplier_id: uuid.UUID) -> SupplierDetail:
    d = await _load(session)
    s = d.suppliers.get(supplier_id)
    if s is None:
        raise NotFound("Supplier not found.")
    qc_by_po: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
    for e in (
        await session.execute(select(PoEvent).where(PoEvent.kind == "qc").order_by(PoEvent.created_at))
    ).scalars():
        qc_by_po[e.po_id].append(e.data or {})
    out = []
    seen_po: set[uuid.UUID] = set()
    for po, at in reversed(d.gates):
        if po.supplier_id != supplier_id:
            continue
        ln = d.lines[po.id][0] if d.lines[po.id] else None
        m = d.materials.get(ln.material_id) if ln else None
        qc = qc_by_po.get(po.id, [])
        first = po.id not in seen_po
        seen_po.add(po.id)
        out.append(DeliveryOut(
            po_number=po.number, material=m.name if m else "", unit=m.unit if m else "",
            promised_date=po.promised_date, arrived=at.date(),
            on_time=(at.date() <= po.promised_date) if po.promised_date else None,
            lead_days=(at.date() - po.approved_at.date()).days if po.approved_at and first else None,
            accepted=sum((Decimal(str(x.get("accepted", 0))) for x in qc), Decimal(0)) if qc else None,
            rejected=sum((Decimal(str(x.get("rejected", 0))) for x in qc), Decimal(0)) if qc else None,
        ))  # fmt: skip
    return SupplierDetail(
        id=s.id,
        name=s.name,
        deliveries=out[:50],
        quotes=[_quote_out(d, q) for q in reversed(d.quotes) if q.supplier_id == supplier_id][:20],
        open_pos=sorted(
            po.number for po in d.pos.values() if po.supplier_id == supplier_id and po.status in OPEN
        ),
    )


# ---- quotes and the preferred supplier --------------------------------------------------------------


async def _supplier(session: AsyncSession, name: str) -> Supplier:
    name = name.strip()
    sup = (await session.execute(select(Supplier).where(Supplier.name == name))).scalar_one_or_none()
    if sup is None:
        sup = Supplier(name=name)
        session.add(sup)
        await session.flush()
    return sup


async def request_quotes(session: AsyncSession, actor: uuid.UUID, body: QuoteRequestIn) -> list[QuoteOut]:
    """Ask suppliers for a quote (recorded; the purchaser contacts them and records each reply)."""
    mat = await session.get(Material, body.material_id)
    if mat is None:
        raise NotFound("Material not found.")
    names = list(dict.fromkeys(n.strip() for n in body.suppliers if n.strip()))
    if not names:
        raise DomainError("Name at least one supplier.")
    made = []
    for n in names:
        sup = await _supplier(session, n)
        q = SupplierQuote(supplier_id=sup.id, material_id=mat.id, status="requested", quantity=body.quantity,
                          note=body.note, requested_by=actor)  # fmt: skip
        session.add(q)
        made.append(q)
    await session.flush()
    for q in made:
        await audit.record(session, actor_id=actor, action="create", entity_type="supplier_quote", entity_id=q.id,
                           summary=f"Quote requested · {mat.code} from {(await session.get(Supplier, q.supplier_id)).name}")  # type: ignore[union-attr]  # fmt: skip
    d = await _load(session)
    return [_quote_out(d, q) for q in made]


async def reply_quote(
    session: AsyncSession, actor: uuid.UUID, quote_id: uuid.UUID, body: QuoteReplyIn
) -> QuoteOut:
    q = await session.get(SupplierQuote, quote_id, with_for_update=True)
    if q is None:
        raise NotFound("Quote not found.")
    if body.valid_until < clock.today():
        raise DomainError("The quote must still be valid today.")
    before = {"status": q.status, "rate_paise": q.rate_paise}
    q.status, q.rate_paise, q.lead_days, q.valid_until = (
        "received",
        body.rate_paise,
        body.lead_days,
        body.valid_until,
    )
    q.replied_at = datetime.now(UTC)
    if body.note:
        q.note = body.note
    await audit.record(session, actor_id=actor, action="update", entity_type="supplier_quote", entity_id=q.id,
                       summary=f"Quote received · ₹{body.rate_paise / 100:,.0f} per unit, {body.lead_days} days",
                       before=before, after={"status": q.status, "rate_paise": q.rate_paise})  # fmt: skip
    await session.flush()
    return _quote_out(await _load(session), q)


async def set_preferred(session: AsyncSession, actor: uuid.UUID, body: PreferredIn) -> SupplierRow | None:
    """Select vendor: the supplier Raise PO pre-fills for this material (the owner still approves every PO)."""
    mat = await session.get(Material, body.material_id)
    sup = await session.get(Supplier, body.supplier_id)
    if mat is None or sup is None:
        raise NotFound("Material or supplier not found.")
    p = (
        await session.execute(select(PreferredSupplier).where(PreferredSupplier.material_id == mat.id))
    ).scalar_one_or_none()
    before = {"supplier_id": str(p.supplier_id)} if p else None
    if p is None:
        p = PreferredSupplier(material_id=mat.id, supplier_id=sup.id, set_by=actor)
        session.add(p)
    else:
        p.supplier_id, p.set_by = sup.id, actor
    await session.flush()
    await audit.record(session, actor_id=actor, action="update", entity_type="preferred_supplier", entity_id=p.id,
                       summary=f"{sup.name} selected for {mat.code}", before=before,
                       after={"supplier_id": str(sup.id)})  # fmt: skip
    out = await comparison(session)
    return next((r for r in out.rows if r.material_id == mat.id and r.supplier_id == sup.id), None)


async def preferred_for(session: AsyncSession) -> dict[uuid.UUID, tuple[str, int | None]]:
    """Material -> (preferred supplier, its rate: valid quote, else last price paid). For Raise PO."""
    out = await comparison(session)
    return {r.material_id: (r.supplier, r.rate_paise) for r in out.rows if r.preferred}
