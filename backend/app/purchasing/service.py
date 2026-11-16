"""Purchasing: inventory (stock, reserved, on order, status), purchase orders and the stock ledger.

Sources of truth
- In stock: the ledger (`stock_movements`); `material_stock.on_hand` keeps its total.
- On order: lines of POs that are ordered / confirmed, minus what was received. `material_stock.next_arrival_*`
  mirrors the earliest one so Planning (which reads one delivery per material) sees real POs.
- Reserved / needed: Planning's `material_demand()` (approved plans reserve; the working plan needs).
"""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Material, MaterialStock
from app.core import audit, clock, counters, events
from app.core.errors import DomainError, NotFound
from app.core.models import User
from app.orders import service as orders_service
from app.planning import service as planning
from app.purchasing.models import (
    INCOMING,
    OPEN,
    PoEvent,
    PurchaseOrder,
    PurchaseOrderLine,
    StockMovement,
    Supplier,
)
from app.purchasing.schemas import (
    ConfirmIn,
    DispatchIn,
    FollowUpIn,
    GateEntryIn,
    Incoming,
    InventoryOut,
    Kpis,
    MaterialRow,
    Need,
    PoDetail,
    PoEditIn,
    PoEventOut,
    PoLine,
    PoOut,
    PoRaiseIn,
    PurchaseKpis,
    PurchasesOut,
    QcIn,
    Shortfall,
)

ZERO = Decimal("0")
STATUS_ORDER = {"critical_short": 0, "low_stock": 1, "in_transit": 2, "adequate": 3}


def _q(x: Decimal, unit: str) -> str:
    """'2.2 t', '45,000 pcs'."""
    v = f"{x:,.3f}".rstrip("0").rstrip(".")
    return f"{v} {unit}"


def _day(d: date) -> str:
    return d.strftime("%a %-d %b")


# ---- ledger + what Planning reads ---------------------------------------------------------------


async def _stock_row(session: AsyncSession, material_id: uuid.UUID) -> MaterialStock:
    st = (
        await session.execute(select(MaterialStock).where(MaterialStock.material_id == material_id))
    ).scalar_one_or_none()
    if st is None:
        st = MaterialStock(material_id=material_id, on_hand=ZERO)
        session.add(st)
        await session.flush()
    return st


async def post_movement(session: AsyncSession, material_id: uuid.UUID, qty: Decimal, kind: str, *,
                        actor: uuid.UUID | None = None, po_line_id: uuid.UUID | None = None,
                        note: str | None = None) -> None:  # fmt: skip
    """The only way stock changes: one ledger row, and the cached total on `material_stock`."""
    session.add(StockMovement(material_id=material_id, quantity=qty, kind=kind, po_line_id=po_line_id,
                              note=note, actor_id=actor))  # fmt: skip
    st = await _stock_row(session, material_id)
    st.on_hand = (st.on_hand or ZERO) + qty
    await session.flush()


async def sync_incoming(session: AsyncSession, material_ids: set[uuid.UUID]) -> None:
    """Mirror the earliest delivery on order (ordered / confirmed POs) onto `material_stock.next_arrival_*`."""
    for mid in material_ids:
        rows = (await session.execute(
            select(PurchaseOrderLine, PurchaseOrder).join(PurchaseOrder, PurchaseOrder.id == PurchaseOrderLine.po_id)
            .where(PurchaseOrderLine.material_id == mid, PurchaseOrder.status.in_(INCOMING))
        )).all()  # fmt: skip
        left = [
            (po.expected_date, ln.quantity - ln.received_qty)
            for ln, po in rows
            if ln.quantity > ln.received_qty
        ]
        st = await _stock_row(session, mid)
        if left:
            first = min(d for d, _ in left)
            st.next_arrival_date = first
            st.next_arrival_qty = sum((q for d, q in left if d == first), ZERO)
        else:
            st.next_arrival_date, st.next_arrival_qty = None, None
    await session.flush()


# ---- inventory ---------------------------------------------------------------------------------------


async def inventory(session: AsyncSession) -> InventoryOut:
    today = clock.today()
    materials = list((await session.execute(select(Material).order_by(Material.code))).scalars())
    stock = {s.material_id: s for s in (await session.execute(select(MaterialStock))).scalars()}
    demand: dict[uuid.UUID, list[dict[str, Any]]] = defaultdict(list)
    for d in await planning.material_demand(session):
        demand[d["material_id"]].append(d)
    pos = await _open_pos(session)
    incoming: dict[uuid.UUID, list[Incoming]] = defaultdict(list)
    for po in pos:
        for ln in po.lines:
            left = ln.quantity - ln.received_qty
            if left > 0:
                incoming[ln.material_id].append(Incoming(
                    po_id=po.id, po_number=po.number, status=po.status, supplier=po.supplier, quantity=left,
                    expected_date=po.expected_date, confirmed=po.confirmed))  # fmt: skip
    last_supplier = {ln.material_id: po.supplier for po in reversed(pos) for ln in po.lines}

    rows = []
    for m in materials:
        st = stock.get(m.id)
        in_stock = st.on_hand if st else ZERO
        needs = demand.get(m.id, [])
        reserved = sum((d["qty"] for d in needs if d["reserved"]), ZERO)
        inc = sorted(incoming.get(m.id, []), key=lambda i: i.expected_date)
        coming = [i for i in inc if i.status in INCOMING]
        on_order = sum((i.quantity for i in coming), ZERO)
        waiting = sum((i.quantity for i in inc if i.status == "awaiting_approval"), ZERO)
        rows.append(_row(m, in_stock, reserved, on_order, waiting, needs, coming, inc,
                         last_supplier.get(m.id) or m.express_supplier))  # fmt: skip

    kpis = Kpis(
        skus=len(materials),
        below_reorder=sum(1 for r in rows if r.in_stock < r.reorder_level),
        on_order=sum(1 for po in pos if po.status in INCOMING),
        awaiting_approval=sum(1 for po in pos if po.status == "awaiting_approval"),
        stock_value_paise=sum(r.stock_value_paise for r in rows),
    )
    attention = sorted(
        (r for r in rows if r.status != "adequate"), key=lambda r: (STATUS_ORDER[r.status], r.code)
    )
    suppliers = list((await session.execute(select(Supplier.name).order_by(Supplier.name))).scalars())
    return InventoryOut(kpis=kpis, materials=rows, attention=attention, purchase_orders=pos,
                        categories=sorted({m.category for m in materials if m.category}),
                        suppliers=suppliers, today=today)  # fmt: skip


def _row(m: Material, in_stock: Decimal, reserved: Decimal, on_order: Decimal, waiting: Decimal,
         needs: list[dict[str, Any]], coming: list[Incoming], inc: list[Incoming],
         supplier: str | None) -> MaterialRow:  # fmt: skip
    """Status, worst first:
    critical short: stock + deliveries arriving in time can't cover an order that needs it;
    in transit: a PO on the way covers the gap (or tops up a level below reorder);
    low stock: in stock below the reorder level; adequate: none of these."""
    avail, k = in_stock, 0
    short: Shortfall | None = None
    needed_incoming = False
    without = in_stock
    for d in needs:  # in order of need
        while k < len(coming) and coming[k].expected_date <= d["needed_by"]:
            avail += coming[k].quantity
            k += 1
        without -= d["qty"]
        if without < 0:
            needed_incoming = True
        if avail < d["qty"] and short is None:
            short = Shortfall(order_id=d["order_id"], number=d["number"], customer=d["customer"],
                              needed_by=d["needed_by"], short=d["qty"] - max(avail, ZERO))  # fmt: skip
        avail -= d["qty"]
    total_need = sum((d["qty"] for d in needs), ZERO)
    projected = in_stock + on_order + waiting - total_need
    suggested = max(ZERO, m.reorder_level - projected) if projected < m.reorder_level else ZERO
    if short is not None:
        suggested = max(suggested, short.short)
    nxt = next(iter(needs), None)
    next_need = f"Needed for {nxt['number']} ({nxt['customer']})" if nxt else None

    if short is not None:
        status = "critical_short"
        reason = f"Short by {_q(short.short, m.unit)} for {short.number} ({short.customer})"
    elif coming and (needed_incoming or in_stock < m.reorder_level):
        status = "in_transit"
        first = coming[0]
        reason = f"Arriving {_day(first.expected_date)} · {first.supplier}"
    elif in_stock < m.reorder_level:
        status = "low_stock"
        reason = next_need or f"Below the reorder level of {_q(m.reorder_level, m.unit)}"
    else:
        status = "adequate"
        reason = next_need or "Enough stock"
    return MaterialRow(
        id=m.id, code=m.code, name=m.name, unit=m.unit, category=m.category, grade=m.grade,
        in_stock=in_stock, reserved=reserved, free=in_stock - reserved, on_order=on_order, awaiting_approval=waiting,
        reorder_level=m.reorder_level, price_per_unit_paise=m.price_per_unit_paise,
        stock_value_paise=int(in_stock * m.price_per_unit_paise), status=status, reason=reason, shortfall=short,
        next_need=next_need, incoming=inc, suggested_qty=suggested.quantize(Decimal("0.001")), supplier=supplier,
        needs=[Need(number=d["number"], customer=d["customer"], needed_by=d["needed_by"], qty=d["qty"]) for d in needs],
    )  # fmt: skip


# ---- purchase orders -----------------------------------------------------------------------------------

PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
STAGE_RANK = {"pending_approval": 0, "delayed": 1, "at_gate": 2, "arriving_today": 3}


def _days(n: int) -> str:
    return f"{n} day{'s' * (n != 1)}"


class _Ctx:
    """What a PO's stage and priority depend on, loaded once per request."""

    def __init__(self, today: date, need: dict[tuple[uuid.UUID, str], date], prio: dict[str, str]):
        self.today, self.need, self.prio = today, need, prio


async def _ctx(session: AsyncSession, pos: list[PurchaseOrder]) -> _Ctx:
    need: dict[tuple[uuid.UUID, str], date] = {}
    for d in await planning.material_demand(session):
        k = (d["material_id"], d["number"])
        need[k] = min(need.get(k, d["needed_by"]), d["needed_by"])
    nums = sorted({n for po in pos for n in (po.order_numbers or [])})
    return _Ctx(clock.today(), need, await orders_service.priorities(session, nums))


def _stage(po: PurchaseOrder, needed_by: date | None, today: date) -> tuple[str, str]:
    """(stage, text) as the screens show it.
    Delayed: past its expected date and not arrived, or the supplier's date is later than a linked order
    needs the material ("behind schedule")."""
    if po.status == "cancelled":
        return "cancelled", f"Cancelled · {po.cancel_reason}" if po.cancel_reason else "Cancelled"
    if po.status == "received":
        return "received", "Received and passed QC"
    if po.status == "at_gate":
        return "at_gate", f"Gate entry logged · {po.gate_ref} · ready for QC"
    behind = (po.expected_date - needed_by).days if needed_by and po.expected_date > needed_by else 0
    if po.status == "awaiting_approval":
        return "pending_approval", (f"Delivery {_day(po.expected_date)} · {_days(behind)} after the order needs it"
                                    if behind else f"Delivery {_day(po.expected_date)}")  # fmt: skip
    overdue = (today - po.expected_date).days if po.expected_date < today else 0
    if overdue or behind:
        n = max(overdue, behind)
        why = "overdue" if overdue >= behind else "after the order needs it"
        return "delayed", f"{_days(n)} behind schedule ({why})"
    if po.expected_date == today:
        return "arriving_today", "Arriving today · log the gate entry"
    if po.status == "dispatched":
        return "in_transit", f"Dispatched · arriving {_day(po.expected_date)}"
    if po.status == "confirmed":
        return "confirmed", f"Supplier confirmed {_day(po.expected_date)}"
    return "sent", f"Sent to the supplier · asked for {_day(po.expected_date)}"


async def _po_out(session: AsyncSession, po: PurchaseOrder, ctx: _Ctx) -> PoOut:
    sup = await session.get(Supplier, po.supplier_id)
    lines = (await session.execute(
        select(PurchaseOrderLine, Material).join(Material, Material.id == PurchaseOrderLine.material_id)
        .where(PurchaseOrderLine.po_id == po.id)
    )).all()  # fmt: skip
    nums = list(po.order_numbers or [])
    needs = [
        ctx.need[(ln.material_id, n)] for ln, _ in lines for n in nums if (ln.material_id, n) in ctx.need
    ]
    needed_by = min(needs) if needs else None
    prios = [ctx.prio[n] for n in nums if n in ctx.prio]
    priority = min(prios, key=lambda p: PRIORITY_RANK.get(p, 1)) if prios else (po.priority or "medium")
    stage, text = _stage(po, needed_by, ctx.today)
    still = sum(((ln.quantity - ln.received_qty) * ln.price_per_unit_paise for ln, _ in lines), Decimal(0))
    return PoOut(
        id=po.id, number=po.number, supplier=sup.name if sup else "", status=po.status,
        expected_date=po.expected_date, confirmed=po.confirmed, note=po.note, source=po.source,
        created_at=po.created_at, approved_at=po.approved_at, cancel_reason=po.cancel_reason,
        value_paise=int(sum(ln.quantity * ln.price_per_unit_paise for ln, _ in lines)),
        lines=[PoLine(id=ln.id, material_id=ln.material_id, material=m.name, code=m.code, quantity=ln.quantity,
                      unit=ln.unit, price_per_unit_paise=ln.price_per_unit_paise, received_qty=ln.received_qty,
                      rejected_qty=ln.rejected_qty or ZERO)
               for ln, m in lines],
        stage=stage, stage_text=text, priority=priority, orders=nums, needed_by=needed_by,
        open_value_paise=int(still) if po.status in OPEN else 0, dispatched_at=po.dispatched_at,
        gate_qty=po.gate_qty, gate_ref=po.gate_ref, gate_at=po.gate_at,
    )  # fmt: skip


async def _open_pos(session: AsyncSession) -> list[PoOut]:
    q = select(PurchaseOrder).where(PurchaseOrder.status.in_(OPEN)).order_by(PurchaseOrder.created_at.desc())
    pos = list((await session.execute(q)).scalars())
    ctx = await _ctx(session, pos)
    return [await _po_out(session, po, ctx) for po in pos]


async def list_pos(session: AsyncSession) -> list[PoOut]:
    pos = list(
        (await session.execute(select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc()))).scalars()
    )
    ctx = await _ctx(session, pos)
    return [await _po_out(session, po, ctx) for po in pos]


async def purchases(session: AsyncSession) -> PurchasesOut:
    """Raw Material Purchase: every PO with its stage, KPIs and the POs that need attention."""
    rows = await list_pos(session)
    open_ = [r for r in rows if r.status in OPEN]
    attention = sorted((r for r in open_ if r.stage in STAGE_RANK),
                       key=lambda r: (STAGE_RANK[r.stage], r.expected_date, r.number))  # fmt: skip
    kpis = PurchaseKpis(
        open=len(open_),
        pending_approval=sum(1 for r in open_ if r.status == "awaiting_approval"),
        in_transit=sum(1 for r in open_ if r.status in ("dispatched", "at_gate")),
        open_spend_paise=sum(r.open_value_paise for r in open_),
    )
    suppliers = list((await session.execute(select(Supplier.name).order_by(Supplier.name))).scalars())
    return PurchasesOut(kpis=kpis, attention=attention, purchase_orders=rows, suppliers=suppliers,
                        today=clock.today())  # fmt: skip


async def get_po(session: AsyncSession, po_id: uuid.UUID) -> PoDetail:
    po = await session.get(PurchaseOrder, po_id)
    if po is None:
        raise NotFound("Purchase order not found.")
    return await _detail(session, po)


async def _detail(session: AsyncSession, po: PurchaseOrder) -> PoDetail:
    out = await _po_out(session, po, await _ctx(session, [po]))
    rows = (await session.execute(
        select(PoEvent, User.full_name).outerjoin(User, User.id == PoEvent.actor_id)
        .where(PoEvent.po_id == po.id).order_by(PoEvent.created_at, PoEvent.id)
    )).all()  # fmt: skip
    return PoDetail(**out.model_dump(), events=[PoEventOut(kind=e.kind, summary=e.summary, at=e.created_at, by=name)
                                                for e, name in rows])  # fmt: skip


async def _get(session: AsyncSession, po_id: uuid.UUID) -> PurchaseOrder:
    po = await session.get(PurchaseOrder, po_id, with_for_update=True)
    if po is None:
        raise NotFound("Purchase order not found.")
    return po


async def _lines(session: AsyncSession, po: PurchaseOrder) -> list[PurchaseOrderLine]:
    q = select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id)
    return list((await session.execute(q)).scalars())


async def _materials_of(session: AsyncSession, po: PurchaseOrder) -> set[uuid.UUID]:
    return {ln.material_id for ln in await _lines(session, po)}


async def _log(session: AsyncSession, po: PurchaseOrder, actor: uuid.UUID | None, kind: str, summary: str,
               data: dict[str, Any] | None = None) -> None:  # fmt: skip
    """One step of the PO: its timeline (insert-only) and the audit log, in the same transaction."""
    # exact time (not the transaction's start) so steps taken in one request keep their order
    session.add(PoEvent(po_id=po.id, kind=kind, summary=summary, data=data or {}, actor_id=actor,
                        created_at=datetime.now(UTC)))  # fmt: skip
    await audit.record(session, actor_id=actor, action="create" if kind == "raised" else "update",
                       entity_type="purchase_order", entity_id=po.id, summary=f"{po.number}: {summary}")  # fmt: skip
    await session.flush()


async def _supplier(session: AsyncSession, name: str) -> Supplier:
    name = name.strip()
    sup = (await session.execute(select(Supplier).where(Supplier.name == name))).scalar_one_or_none()
    if sup is None:
        sup = Supplier(name=name)
        session.add(sup)
        await session.flush()
    return sup


async def _check_orders(session: AsyncSession, numbers: list[str]) -> list[str]:
    nums = list(dict.fromkeys(n.strip() for n in numbers if n.strip()))
    known = await orders_service.priorities(session, nums)
    missing = [n for n in nums if n not in known]
    if missing:
        raise DomainError("Unknown order: " + ", ".join(missing), details={"orders": missing})
    return nums


async def raise_po(session: AsyncSession, actor: uuid.UUID, body: PoRaiseIn) -> PoDetail:
    """Purchaser / owner raises a PO. It waits for the owner's approval before it counts as on order."""
    mat = await session.get(Material, body.material_id)
    if mat is None:
        raise NotFound("Material not found.")
    if body.expected_date < clock.today():
        raise DomainError("The expected date can't be in the past.")
    sup = await _supplier(session, body.supplier)
    nums = await _check_orders(session, body.order_numbers)
    n = await counters.next_value(session, "po", start=0)
    po = PurchaseOrder(number=f"PO-{n:04d}", supplier_id=sup.id, status="awaiting_approval",
                       expected_date=body.expected_date, note=body.note, raised_by=actor, order_numbers=nums,
                       priority=body.priority)  # fmt: skip
    session.add(po)
    await session.flush()
    session.add(PurchaseOrderLine(po_id=po.id, material_id=mat.id, quantity=body.quantity, unit=mat.unit,
                                  price_per_unit_paise=body.price_per_unit_paise, received_qty=ZERO,
                                  rejected_qty=ZERO))  # fmt: skip
    linked = await planning.link_requests(session, mat.id, po.number)
    if linked is not None:
        po.source = "planning"  # it takes over Planning's purchase request for this material
        po.order_numbers = nums + [x for x in linked if x not in nums]
    await _log(session, po, actor, "raised", f"Raised · {_q(body.quantity, mat.unit)} {mat.name} from {sup.name}"
               + (f" for {', '.join(po.order_numbers)}" if po.order_numbers else ""))  # fmt: skip
    return await _detail(session, po)


async def edit_po(session: AsyncSession, actor: uuid.UUID, po_id: uuid.UUID, body: PoEditIn) -> PoDetail:
    """Change a PO while it waits for the owner's approval."""
    po = await _get(session, po_id)
    if po.status != "awaiting_approval":
        raise DomainError("Only a PO awaiting approval can be changed.")
    line = (await _lines(session, po))[0]
    changes = []
    if body.supplier is not None:
        sup = await _supplier(session, body.supplier)
        if sup.id != po.supplier_id:
            po.supplier_id = sup.id
            changes.append(f"supplier {sup.name}")
    if body.quantity is not None and body.quantity != line.quantity:
        line.quantity = body.quantity
        changes.append(f"quantity {_q(body.quantity, line.unit)}")
    if body.price_per_unit_paise is not None and body.price_per_unit_paise != line.price_per_unit_paise:
        line.price_per_unit_paise = body.price_per_unit_paise
        changes.append(f"price ₹{body.price_per_unit_paise / 100:,.2f} per {line.unit}")
    if body.expected_date is not None and body.expected_date != po.expected_date:
        if body.expected_date < clock.today():
            raise DomainError("The expected date can't be in the past.")
        po.expected_date = body.expected_date
        changes.append(f"delivery {_day(body.expected_date)}")
    if body.order_numbers is not None:
        nums = await _check_orders(session, body.order_numbers)
        if nums != list(po.order_numbers or []):
            po.order_numbers = nums
            changes.append("linked orders " + (", ".join(nums) or "none"))
    if body.priority is not None and body.priority != po.priority:
        po.priority = body.priority
        changes.append(f"priority {body.priority}")
    if body.note is not None and body.note != (po.note or ""):
        po.note = body.note or None
        changes.append("note")
    if changes:
        await _log(session, po, actor, "edited", "Changed · " + ", ".join(changes))
    return await _detail(session, po)


async def approve_po(session: AsyncSession, actor: uuid.UUID, po_id: uuid.UUID) -> PoDetail:
    po = await _get(session, po_id)
    if po.status != "awaiting_approval":
        raise DomainError("Only a PO awaiting approval can be approved.")
    po.status, po.approved_by, po.approved_at = "ordered", actor, datetime.now(UTC)
    await planning.update_requests(session, po.number, "ordered")
    await sync_incoming(session, await _materials_of(session, po))
    await _log(session, po, actor, "approved", "Approved by the owner · PO sent to the supplier")
    return await _detail(session, po)


async def confirm_po(session: AsyncSession, actor: uuid.UUID, po_id: uuid.UUID, body: ConfirmIn) -> PoDetail:
    """The supplier confirmed the order and its delivery date."""
    po = await _get(session, po_id)
    if po.status not in ("ordered", "confirmed", "dispatched"):
        raise DomainError("Only a PO sent to the supplier can be confirmed.")
    if po.status == "ordered":
        po.status = "confirmed"
    po.confirmed, po.expected_date = True, body.expected_date
    await planning.update_requests(session, po.number, po.status)
    await sync_incoming(session, await _materials_of(session, po))
    await _log(session, po, actor, "confirmed", f"Supplier confirmed delivery {_day(body.expected_date)}")
    return await _detail(session, po)


async def dispatch_po(
    session: AsyncSession, actor: uuid.UUID, po_id: uuid.UUID, body: DispatchIn
) -> PoDetail:
    """The supplier dispatched the goods: in transit."""
    po = await _get(session, po_id)
    if po.status not in ("ordered", "confirmed"):
        raise DomainError("Only a PO sent to the supplier can be marked dispatched.")
    po.status, po.dispatched_at = "dispatched", datetime.now(UTC)
    if body.expected_date is not None:
        po.expected_date = body.expected_date
    await planning.update_requests(session, po.number, "dispatched")
    await sync_incoming(session, await _materials_of(session, po))
    await _log(session, po, actor, "dispatched", f"Dispatched · arriving {_day(po.expected_date)}"
               + (f" · {body.note}" if body.note else ""))  # fmt: skip
    return await _detail(session, po)


async def gate_entry(
    session: AsyncSession, actor: uuid.UUID, po_id: uuid.UUID, body: GateEntryIn
) -> PoDetail:
    """The goods arrived at the gate (challan / vehicle no.): waiting for QC, not in stock yet."""
    po = await _get(session, po_id)
    if po.status not in ("ordered", "confirmed", "dispatched"):
        raise DomainError("Only an approved PO that hasn't arrived can get a gate entry.")
    line = (await _lines(session, po))[0]
    left = line.quantity - line.received_qty
    if body.quantity > left:
        raise DomainError(f"Only {_q(left, line.unit)} is still to come on this PO.")
    po.status, po.gate_qty, po.gate_ref, po.gate_at = (
        "at_gate",
        body.quantity,
        body.reference.strip(),
        datetime.now(UTC),
    )
    await planning.update_requests(session, po.number, "at_gate")
    await sync_incoming(session, {line.material_id})
    await _log(session, po, actor, "gate_entry", f"Gate entry · {_q(body.quantity, line.unit)} · {po.gate_ref}"
               + (f" · {body.note}" if body.note else ""), {"qty": str(body.quantity), "ref": po.gate_ref})  # fmt: skip
    return await _detail(session, po)


async def quality_check(session: AsyncSession, actor: uuid.UUID, po_id: uuid.UUID, body: QcIn) -> PoDetail:
    """QC of the gate entry: the accepted quantity goes into stock (ledger); the rejected quantity goes back to
    the supplier and is still owed. Everything accepted -> received, and Production can use the material."""
    po = await _get(session, po_id)
    if po.status != "at_gate" or po.gate_qty is None:
        raise DomainError("There is no gate entry waiting for QC on this PO.")
    if body.accepted + body.rejected != po.gate_qty:
        raise DomainError(
            f"Accepted + rejected must add up to the {_q(po.gate_qty, '').strip()} at the gate."
        )
    if body.rejected > 0 and not (body.reason or "").strip():
        raise DomainError("Say why the rejected quantity was rejected.")
    line = (await _lines(session, po))[0]
    mat = await session.get(Material, line.material_id)
    assert mat is not None
    if body.accepted > 0:
        line.received_qty = line.received_qty + body.accepted
        await post_movement(session, line.material_id, body.accepted, "receipt", actor=actor, po_line_id=line.id,
                            note=f"{po.number} · QC passed · {po.gate_ref}")  # fmt: skip
    if body.rejected > 0:
        line.rejected_qty = (line.rejected_qty or ZERO) + body.rejected
    ref = po.gate_ref
    po.gate_qty, po.gate_ref, po.gate_at = None, None, None
    done = line.received_qty >= line.quantity
    po.status = "received" if done else ("confirmed" if po.confirmed else "ordered")
    if not done:
        po.dispatched_at = None  # the rest still has to be sent
    await planning.update_requests(session, po.number, po.status)
    await sync_incoming(session, {line.material_id})
    parts = [f"{_q(body.accepted, line.unit)} accepted into stock"]
    if body.rejected > 0:
        parts.append(f"{_q(body.rejected, line.unit)} rejected: {body.reason}")
    if not done:
        parts.append(f"{_q(line.quantity - line.received_qty, line.unit)} still to come")
    await _log(session, po, actor, "qc", "QC · " + " · ".join(parts),
               {"accepted": str(body.accepted), "rejected": str(body.rejected), "ref": ref})  # fmt: skip
    if body.accepted > 0:
        # Production (next module) picks this up: the material for these orders is in stock now
        await events.emit(session, "purchasing.material_received", {
            "po": po.number, "material_id": str(line.material_id), "material": mat.code,
            "quantity": str(body.accepted), "unit": line.unit, "orders": list(po.order_numbers or []),
        })  # fmt: skip
    return await _detail(session, po)


async def follow_up(session: AsyncSession, actor: uuid.UUID, po_id: uuid.UUID, body: FollowUpIn) -> PoDetail:
    """Chased the supplier: the note, and the new date they promised (if any)."""
    po = await _get(session, po_id)
    if po.status not in INCOMING:
        raise DomainError("Only an approved PO that hasn't been received can be followed up.")
    text_ = f"Followed up · {body.note}"
    if body.promised_date is not None and body.promised_date != po.expected_date:
        text_ += f" · supplier now promises {_day(body.promised_date)} (was {_day(po.expected_date)})"
        po.expected_date = body.promised_date
        await sync_incoming(session, await _materials_of(session, po))
    await _log(session, po, actor, "follow_up", text_)
    return await _detail(session, po)


async def cancel_po(session: AsyncSession, actor: uuid.UUID, po_id: uuid.UUID, reason: str) -> PoDetail:
    po = await _get(session, po_id)
    if po.status not in OPEN:
        raise DomainError("Only an open PO can be cancelled.")
    if po.status == "at_gate":
        raise DomainError("The goods are at the gate: finish QC first.")
    if any(ln.received_qty > 0 for ln in await _lines(session, po)):
        raise DomainError("Part of this PO was already received; it can't be cancelled.")
    po.status, po.cancel_reason = "cancelled", reason
    await planning.update_requests(session, po.number, "cancelled")
    await sync_incoming(session, await _materials_of(session, po))
    await _log(session, po, actor, "cancelled", f"Cancelled: {reason}")
    return await _detail(session, po)
