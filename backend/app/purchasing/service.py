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
from app.core import audit, clock, counters
from app.core.errors import DomainError, NotFound
from app.planning import service as planning
from app.purchasing.models import INCOMING, OPEN, PurchaseOrder, PurchaseOrderLine, StockMovement, Supplier
from app.purchasing.schemas import (
    ConfirmIn,
    Incoming,
    InventoryOut,
    Kpis,
    MaterialRow,
    PoLine,
    PoOut,
    PoRaiseIn,
    ReceiveIn,
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
    )  # fmt: skip


# ---- purchase orders -----------------------------------------------------------------------------------


async def _po_out(session: AsyncSession, po: PurchaseOrder) -> PoOut:
    sup = await session.get(Supplier, po.supplier_id)
    lines = (await session.execute(
        select(PurchaseOrderLine, Material).join(Material, Material.id == PurchaseOrderLine.material_id)
        .where(PurchaseOrderLine.po_id == po.id)
    )).all()  # fmt: skip
    return PoOut(
        id=po.id, number=po.number, supplier=sup.name if sup else "", status=po.status,
        expected_date=po.expected_date, confirmed=po.confirmed, note=po.note, source=po.source,
        created_at=po.created_at, approved_at=po.approved_at, cancel_reason=po.cancel_reason,
        value_paise=int(sum(ln.quantity * ln.price_per_unit_paise for ln, _ in lines)),
        lines=[PoLine(id=ln.id, material_id=ln.material_id, material=m.name, code=m.code, quantity=ln.quantity,
                      unit=ln.unit, price_per_unit_paise=ln.price_per_unit_paise, received_qty=ln.received_qty)
               for ln, m in lines],
    )  # fmt: skip


async def _open_pos(session: AsyncSession) -> list[PoOut]:
    q = select(PurchaseOrder).where(PurchaseOrder.status.in_(OPEN)).order_by(PurchaseOrder.created_at.desc())
    return [await _po_out(session, po) for po in (await session.execute(q)).scalars()]


async def list_pos(session: AsyncSession) -> list[PoOut]:
    q = select(PurchaseOrder).order_by(PurchaseOrder.created_at.desc())
    return [await _po_out(session, po) for po in (await session.execute(q)).scalars()]


async def _get(session: AsyncSession, po_id: uuid.UUID) -> PurchaseOrder:
    po = await session.get(PurchaseOrder, po_id, with_for_update=True)
    if po is None:
        raise NotFound("Purchase order not found.")
    return po


async def _materials_of(session: AsyncSession, po: PurchaseOrder) -> set[uuid.UUID]:
    q = select(PurchaseOrderLine.material_id).where(PurchaseOrderLine.po_id == po.id)
    return set((await session.execute(q)).scalars())


async def raise_po(session: AsyncSession, actor: uuid.UUID, body: PoRaiseIn) -> PoOut:
    """Purchaser / owner raises a PO. It waits for the owner's approval before it counts as on order."""
    mat = await session.get(Material, body.material_id)
    if mat is None:
        raise NotFound("Material not found.")
    if body.expected_date < clock.today():
        raise DomainError("The expected date can't be in the past.")
    name = body.supplier.strip()
    sup = (await session.execute(select(Supplier).where(Supplier.name == name))).scalar_one_or_none()
    if sup is None:
        sup = Supplier(name=name)
        session.add(sup)
        await session.flush()
    n = await counters.next_value(session, "po", start=0)
    po = PurchaseOrder(number=f"PO-{n:04d}", supplier_id=sup.id, status="awaiting_approval",
                       expected_date=body.expected_date, note=body.note, raised_by=actor)  # fmt: skip
    session.add(po)
    await session.flush()
    session.add(PurchaseOrderLine(po_id=po.id, material_id=mat.id, quantity=body.quantity, unit=mat.unit,
                                  price_per_unit_paise=body.price_per_unit_paise, received_qty=ZERO))  # fmt: skip
    if await planning.link_requests(session, mat.id, po.number):
        po.source = "planning"  # it takes over Planning's purchase request for this material
    await audit.record(session, actor_id=actor, action="create", entity_type="purchase_order", entity_id=po.id,
                       summary=f"{po.number} raised · {_q(body.quantity, mat.unit)} {mat.name} from {name}")  # fmt: skip
    await session.flush()
    return await _po_out(session, po)


async def approve_po(session: AsyncSession, actor: uuid.UUID, po_id: uuid.UUID) -> PoOut:
    po = await _get(session, po_id)
    if po.status != "awaiting_approval":
        raise DomainError("Only a PO awaiting approval can be approved.")
    po.status, po.approved_by, po.approved_at = "ordered", actor, datetime.now(UTC)
    await planning.update_requests(session, po.number, "ordered")
    await sync_incoming(session, await _materials_of(session, po))
    await audit.record(session, actor_id=actor, action="update", entity_type="purchase_order", entity_id=po.id,
                       summary=f"{po.number} approved · ordered")  # fmt: skip
    return await _po_out(session, po)


async def confirm_po(session: AsyncSession, actor: uuid.UUID, po_id: uuid.UUID, body: ConfirmIn) -> PoOut:
    """The supplier confirmed the order and its delivery date."""
    po = await _get(session, po_id)
    if po.status not in INCOMING:
        raise DomainError("Only an ordered PO can be confirmed.")
    po.status, po.confirmed, po.expected_date = "confirmed", True, body.expected_date
    await planning.update_requests(session, po.number, "confirmed")
    await sync_incoming(session, await _materials_of(session, po))
    await audit.record(session, actor_id=actor, action="update", entity_type="purchase_order", entity_id=po.id,
                       summary=f"{po.number} confirmed by the supplier for {body.expected_date.isoformat()}")  # fmt: skip
    return await _po_out(session, po)


async def receive(session: AsyncSession, actor: uuid.UUID, po_id: uuid.UUID, body: ReceiveIn) -> PoOut:
    """Goods received (all or part of a line): stock goes up through the ledger."""
    po = await _get(session, po_id)
    if po.status not in INCOMING:
        raise DomainError("Only an ordered or confirmed PO can be received.")
    line = await session.get(PurchaseOrderLine, body.line_id)
    if line is None or line.po_id != po.id:
        raise NotFound("That line isn't on this PO.")
    left = line.quantity - line.received_qty
    if body.quantity > left:
        raise DomainError(f"Only {_q(left, line.unit)} is still to come on this line.")
    line.received_qty = line.received_qty + body.quantity
    await post_movement(session, line.material_id, body.quantity, "receipt", actor=actor, po_line_id=line.id,
                        note=body.note or f"Received on {po.number}")  # fmt: skip
    lines = (
        await session.execute(select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id))
    ).scalars()
    if all(ln.received_qty >= ln.quantity for ln in lines):
        po.status = "received"
        await planning.update_requests(session, po.number, "received")
    await sync_incoming(session, {line.material_id})
    await audit.record(session, actor_id=actor, action="update", entity_type="purchase_order", entity_id=po.id,
                       summary=f"{po.number} received {_q(body.quantity, line.unit)}")  # fmt: skip
    return await _po_out(session, po)


async def cancel_po(session: AsyncSession, actor: uuid.UUID, po_id: uuid.UUID, reason: str) -> PoOut:
    po = await _get(session, po_id)
    if po.status not in OPEN:
        raise DomainError("Only an open PO can be cancelled.")
    lines = (
        await session.execute(select(PurchaseOrderLine).where(PurchaseOrderLine.po_id == po.id))
    ).scalars()
    if any(ln.received_qty > 0 for ln in lines):
        raise DomainError("Part of this PO was already received; it can't be cancelled.")
    po.status, po.cancel_reason = "cancelled", reason
    await planning.update_requests(session, po.number, "cancelled")
    await sync_incoming(session, await _materials_of(session, po))
    await audit.record(session, actor_id=actor, action="update", entity_type="purchase_order", entity_id=po.id,
                       summary=f"{po.number} cancelled: {reason}")  # fmt: skip
    return await _po_out(session, po)
