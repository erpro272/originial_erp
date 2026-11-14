"""Orders: list/filter, signals (material shortage, schedule risk), ranking, lifecycle.

All numbers on the Orders screens come from here. Shortages allocate the current stock to
open orders in ship-date order, so two orders can't both "use" the same steel.
"""

import math
import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog import service as catalog
from app.catalog.models import Product
from app.core import audit, clock, counters
from app.core.errors import DomainError, NotFound
from app.core.services import kv
from app.customers.models import Customer
from app.orders.models import CURRENT_STATUSES, PAST_STATUSES, TRANSITIONS, Order
from app.orders.schemas import (
    Action,
    MaterialNeed,
    OrderCancel,
    OrderCreate,
    OrderKpis,
    OrderOut,
    OrderUpdate,
    RankingSettings,
    Signal,
)

RANKING_KEY = "order-ranking"
_PRIORITY_RANK = {"high": 0, "medium": 1, "low": 2}
_PRIORITY_SCORE = {"high": 1.0, "medium": 0.5, "low": 0.0}
_TIER_SCORE = {"key": 1.0, "standard": 0.5, "occasional": 0.0}
_STATUS_LABEL = {
    "new": "New", "accepted": "Accepted", "planned": "Planned", "in_production": "Production",
    "completed": "Completed", "shipped": "Shipped", "cancelled": "Cancelled",
}  # fmt: skip


@dataclass
class OrderFilters:
    scope: str = "current"  # current | past | all
    customer_ids: list[uuid.UUID] = field(default_factory=list)
    priorities: list[str] = field(default_factory=list)
    statuses: list[str] = field(default_factory=list)  # real statuses or signal kinds
    q: str | None = None
    max_processing_days: int | None = None
    ship_from: date | None = None
    ship_to: date | None = None
    created_from: date | None = None
    created_to: date | None = None
    planning_only: bool = False


# ---- helpers -----------------------------------------------------------------------------


def working_days_between(start: date, end: date) -> int:
    """Working days from tomorrow up to and including `end` (Sundays off)."""
    if end <= start:
        return 0
    return sum(1 for i in range(1, (end - start).days + 1) if (start + timedelta(i)).weekday() != 6)


def fmt_qty(q: Decimal, unit: str) -> str:
    """2.4 t, 0.03 t, 1,20,000 pcs: precision follows the size of the number."""
    places = Decimal("1") if q >= 100 else Decimal("0.1") if q >= 1 else Decimal("0.001")
    v = q.quantize(places, rounding=ROUND_HALF_UP).normalize()
    if v == v.to_integral():
        n = int(v)
        s = f"{n:,}" if n < 100_000 else _indian(n)
    else:
        s = format(v, "f")
    return f"{s} {unit}"


def _indian(n: int) -> str:
    s = str(n)
    head, tail = s[:-3], s[-3:]
    parts: list[str] = []
    while len(head) > 2:
        parts.insert(0, head[-2:])
        head = head[:-2]
    if head:
        parts.insert(0, head)
    return ",".join([*parts, tail])


def short_date(d: date) -> str:
    return f"{d.day} {d.strftime('%b')}"


def _paise_mul(qty: Decimal, unit_paise: int) -> int:
    return int((qty * unit_paise).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


# ---- loading + computing -------------------------------------------------------------------


@dataclass
class _Row:
    order: Order
    customer: Customer
    product: Product


async def _load(session: AsyncSession, f: OrderFilters | None = None) -> list[_Row]:
    q = (
        select(Order, Customer, Product)
        .join(Customer, Customer.id == Order.customer_id)
        .join(Product, Product.id == Order.product_id)
    )
    if f:
        if f.scope == "current":
            q = q.where(Order.status.in_(CURRENT_STATUSES))
        elif f.scope == "past":
            q = q.where(Order.status.in_(PAST_STATUSES))
        if f.customer_ids:
            q = q.where(Order.customer_id.in_(f.customer_ids))
        if f.priorities:
            q = q.where(Order.priority.in_(f.priorities))
        if f.max_processing_days is not None:
            q = q.where(Order.processing_days <= f.max_processing_days)
        if f.ship_from:
            q = q.where(Order.ship_date >= f.ship_from)
        if f.ship_to:
            q = q.where(Order.ship_date <= f.ship_to)
        if f.created_from:
            q = q.where(Order.created_at >= datetime.combine(f.created_from, datetime.min.time(), UTC))
        if f.created_to:
            q = q.where(
                Order.created_at < datetime.combine(f.created_to + timedelta(1), datetime.min.time(), UTC)
            )
        if f.planning_only:
            q = q.where(Order.marked_for_planning)
        if f.q:
            like = f"%{f.q.strip()}%"
            q = q.where(Order.number.ilike(like) | Customer.name.ilike(like) | Product.name.ilike(like))
    return [_Row(o, c, p) for o, c, p in (await session.execute(q)).all()]


async def _material_needs(session: AsyncSession) -> dict[uuid.UUID, list[MaterialNeed]]:
    """Allocate stock to open orders (earliest ship date first). Returns needs per order."""
    boms = await catalog.boms(session)
    stock = await catalog.stock(session)
    remaining = {mid: s.on_hand for mid, s in stock.items()}
    open_rows = await _load(session, OrderFilters(scope="current"))
    open_rows = [r for r in open_rows if r.order.status in ("new", "accepted", "planned")]
    open_rows.sort(key=lambda r: (r.order.ship_date, _PRIORITY_RANK[r.order.priority], r.order.number))
    needs: dict[uuid.UUID, list[MaterialNeed]] = {}
    for r in open_rows:
        lst = []
        for b in boms.get(r.order.product_id, []):
            req = (b.qty_per_unit * r.order.quantity).quantize(Decimal("0.001"), ROUND_HALF_UP)
            have = remaining.get(b.material_id, Decimal(0))
            used = min(req, max(have, Decimal(0)))
            remaining[b.material_id] = have - used
            lst.append(MaterialNeed(code=b.code, name=b.name, unit=b.unit, required=req,
                                    shortage=req - used))  # fmt: skip
        needs[r.order.id] = lst
    # Orders not competing for stock (in production / past) still show what they use.
    return needs


def _signal(o: Order, needs: list[MaterialNeed], arrivals: dict[str, date | None], today: date) -> Signal:
    if o.status == "cancelled":
        return Signal(kind="cancelled", tone="lo", text="Cancelled", label="Cancelled")
    if o.status in ("completed", "shipped"):
        label = _STATUS_LABEL[o.status]
        return Signal(kind="done", tone="ok", text=label, label=label)
    # Schedule risk: remaining work vs working days left before the ship date.
    work_left = o.processing_days
    if o.status == "in_production" and o.progress_pct is not None:
        work_left = math.ceil(o.processing_days * (100 - o.progress_pct) / 100)
    available = working_days_between(today, o.ship_date)
    if work_left > available:
        behind = work_left - available
        return Signal(
            kind="behind", tone="hi", label="Behind",
            text=f"{behind} day{'s' if behind != 1 else ''} behind · {work_left} days of work, "
                 f"{available} left",
        )  # fmt: skip
    short = [n for n in needs if n.shortage > 0]
    if short:
        worst = max(short, key=lambda n: n.shortage)
        arrives = arrivals.get(worst.code)
        if arrives:
            return Signal(
                kind="waiting", tone="md", label=f"Waiting on {worst.name.split()[-1].lower()}",
                text=f"{worst.name} arriving {short_date(arrives)} · "
                f"{fmt_qty(worst.shortage, worst.unit)} short",
            )  # fmt: skip
        return Signal(
            kind="material_short", tone="md", label="Material short",
            text=f"{worst.name} short · {fmt_qty(worst.shortage, worst.unit)}",
            action=Action(label="Raise PO", href=f"/purchasing?material={worst.code}"),
        )  # fmt: skip
    if o.status == "in_production":
        pct = o.progress_pct or 0
        return Signal(kind="in_production", tone="bl", text=f"In production · {pct}% done",
                      label=f"Production · {pct}%")  # fmt: skip
    if o.status == "planned":
        return Signal(kind="planned", tone="ok", text="Material in · line booked", label="Planned")
    return Signal(kind="ready", tone="ok", text="Material in · ready to plan",
                  label=_STATUS_LABEL[o.status])  # fmt: skip


async def _build(session: AsyncSession, rows: list[_Row]) -> list[OrderOut]:
    needs = await _material_needs(session)
    boms = await catalog.boms(session)
    stock = await catalog.stock(session)
    arrivals = {b.code: stock[b.material_id].next_arrival_date if b.material_id in stock else None
                for lst in boms.values() for b in lst}  # fmt: skip
    today = clock.today()
    out = []
    for r in rows:
        o = r.order
        mats = needs.get(o.id)
        if mats is None:  # not competing for stock: show usage without shortage
            mats = [
                MaterialNeed(code=b.code, name=b.name, unit=b.unit,
                             required=(b.qty_per_unit * o.quantity).quantize(Decimal("0.001")),
                             shortage=Decimal(0))
                for b in boms.get(o.product_id, [])
            ]  # fmt: skip
        summary = ", ".join(f"{m.name} {fmt_qty(m.required, m.unit)}" for m in mats) or None
        unit_cost = int(Decimal(o.cost_paise) / o.quantity) if o.quantity else 0
        out.append(
            OrderOut(
                id=o.id, number=o.number, customer_id=r.customer.id, customer_name=r.customer.name,
                customer_phone=r.customer.phone, customer_email=r.customer.email,
                product_id=r.product.id, product_name=r.product.name, sku=r.product.sku,
                quantity=o.quantity, unit=o.unit, unit_price_paise=o.unit_price_paise,
                unit_cost_paise=unit_cost, sales_paise=o.sales_paise, cost_paise=o.cost_paise,
                profit_paise=o.profit_paise,
                margin_pct=round(o.profit_paise / o.sales_paise * 100, 1) if o.sales_paise else None,
                processing_days=o.processing_days, ship_date=o.ship_date, created_at=o.created_at,
                priority=o.priority, status=o.status, progress_pct=o.progress_pct,
                marked_for_planning=o.marked_for_planning, promised_date=o.promised_date,
                cancel_reason=o.cancel_reason, notes=o.notes, materials=mats,
                materials_summary=summary, signal=_signal(o, mats, arrivals, today),
            )
        )  # fmt: skip
    return out


# ---- queries --------------------------------------------------------------------------------

_SORT_KEYS: dict[str, Any] = {
    "number": lambda o: o.number,
    "customer": lambda o: o.customer_name.lower(),
    "product": lambda o: o.product_name.lower(),
    "quantity": lambda o: o.quantity,
    "sales": lambda o: o.sales_paise,
    "profit": lambda o: o.profit_paise,
    "margin": lambda o: o.margin_pct or 0,
    "processing_days": lambda o: o.processing_days,
    "ship_date": lambda o: o.ship_date,
    "priority": lambda o: _PRIORITY_RANK[o.priority],
    "status": lambda o: o.signal.label,
    "created": lambda o: o.created_at,
}


async def list_orders(
    session: AsyncSession, f: OrderFilters, sort: str = "ship_date", desc: bool = False,
    limit: int = 25, offset: int = 0,
) -> tuple[list[OrderOut], int]:  # fmt: skip
    items = await _build(session, await _load(session, f))
    if f.statuses:
        wanted = set(f.statuses)
        items = [o for o in items if o.status in wanted or o.signal.kind in wanted]
    items.sort(key=lambda o: o.number)  # stable tie-break
    items.sort(key=_SORT_KEYS.get(sort, _SORT_KEYS["ship_date"]), reverse=desc)
    return items[offset : offset + limit], len(items)


async def get_order(session: AsyncSession, order_id: uuid.UUID) -> OrderOut:
    rows = [r for r in await _load(session) if r.order.id == order_id]
    if not rows:
        raise NotFound("Order not found.")
    return (await _build(session, rows))[0]


async def kpis(session: AsyncSession) -> OrderKpis:
    rows = await _load(session, OrderFilters(scope="current"))
    today = clock.today()
    return OrderKpis(
        open_orders=len(rows),
        high_priority=sum(r.order.priority == "high" for r in rows),
        in_production=sum(r.order.status == "in_production" for r in rows),
        ship_in_7_days=sum(today <= r.order.ship_date <= today + timedelta(7) for r in rows),
    )


async def get_ranking(session: AsyncSession) -> RankingSettings:
    try:
        return RankingSettings.model_validate(await kv.get_setting(session, RANKING_KEY))
    except (NotFound, ValueError):
        return RankingSettings()


async def put_ranking(session: AsyncSession, actor: uuid.UUID, s: RankingSettings) -> RankingSettings:
    await kv.put_setting(session, actor, RANKING_KEY, s.model_dump())
    return s


def score_orders(
    items: list[OrderOut], s: RankingSettings, today: date, tiers: dict[uuid.UUID, str]
) -> list[OrderOut]:
    """Rank current orders. Each factor is scaled 0..1 across the open orders."""
    if not items:
        return []
    w = s.weights.model_dump() if s.mode == "weighted" else {s.mode: 1}
    max_qty = max(o.quantity for o in items) or Decimal(1)
    max_profit = max(max(o.profit_paise for o in items), 1)
    ranked = []
    for o in items:
        days = max((o.ship_date - today).days, 0)
        factors = {
            "requirement": float(o.quantity / max_qty),
            "customer": _TIER_SCORE.get(tiers.get(o.customer_id, "standard"), 0.5),
            "profit": max(o.profit_paise, 0) / max_profit,
            "deadline": 1 - min(days, 30) / 30,
            "priority": _PRIORITY_SCORE[o.priority],
        }
        total = sum(w.values())
        o.rank_score = round(sum(factors[k] * v for k, v in w.items()) / total, 4)
        ranked.append(o)
    ranked.sort(key=lambda o: (-(o.rank_score or 0), o.ship_date, o.number))
    return ranked


async def top_orders(session: AsyncSession, n: int = 3) -> list[OrderOut]:
    rows = await _load(session, OrderFilters(scope="current"))
    tiers = {r.customer.id: r.customer.tier for r in rows}
    items = await _build(session, rows)
    return score_orders(items, await get_ranking(session), clock.today(), tiers)[:n]


# ---- writes ---------------------------------------------------------------------------------


def _snapshot(o: Order) -> dict[str, Any]:
    return {
        "customer_id": str(o.customer_id), "product_id": str(o.product_id),
        "quantity": str(o.quantity), "unit_price_paise": o.unit_price_paise,
        "cost_paise": o.cost_paise, "processing_days": o.processing_days,
        "ship_date": o.ship_date.isoformat(), "priority": o.priority, "status": o.status,
        "progress_pct": o.progress_pct, "marked_for_planning": o.marked_for_planning,
        "notes": o.notes,
    }  # fmt: skip


async def _active_customer(session: AsyncSession, cid: uuid.UUID) -> Customer:
    c = await session.get(Customer, cid)
    if c is None or c.merged_into_id or not c.is_active:
        raise DomainError("Choose an active customer.", details={"field": "customer_id"})
    return c


async def create_order(session: AsyncSession, actor: uuid.UUID, body: OrderCreate) -> OrderOut:
    await _active_customer(session, body.customer_id)
    product = await catalog.get_product(session, body.product_id)
    if product is None:
        raise DomainError("Choose a product.", details={"field": "product_id"})
    if body.ship_date < clock.today():
        raise DomainError("Ship date can't be in the past.", details={"field": "ship_date"})
    unit_cost = body.unit_cost_paise if body.unit_cost_paise is not None else product.unit_cost_paise
    number = f"ORD-{await counters.next_value(session, 'order')}"
    o = Order(
        number=number, customer_id=body.customer_id, product_id=product.id,
        quantity=body.quantity, unit=product.unit, unit_price_paise=body.unit_price_paise,
        sales_paise=_paise_mul(body.quantity, body.unit_price_paise),
        cost_paise=_paise_mul(body.quantity, unit_cost),
        processing_days=body.processing_days or product.processing_days,
        ship_date=body.ship_date, priority=body.priority, status=body.status, notes=body.notes,
    )  # fmt: skip
    session.add(o)
    await session.flush()
    await audit.record(session, actor_id=actor, action="create", entity_type="order",
                       entity_id=o.id, summary=f"Order {number} created", after=_snapshot(o))  # fmt: skip
    return await get_order(session, o.id)


async def update_order(
    session: AsyncSession, actor: uuid.UUID, order_id: uuid.UUID, body: OrderUpdate
) -> OrderOut:
    o = await session.get(Order, order_id, with_for_update=True)
    if o is None:
        raise NotFound("Order not found.")
    if o.status in PAST_STATUSES and body.status is None:
        raise DomainError(f"{o.number} is {o.status} and can't be edited.")
    before = _snapshot(o)
    data = body.model_dump(exclude_unset=True)
    if "status" in data and data["status"] != o.status:
        if data["status"] == "cancelled":
            raise DomainError("Use Cancel order to cancel (a reason is required).")
        if data["status"] not in TRANSITIONS[o.status]:
            raise DomainError(f"Can't move an order from {o.status} to {data['status']}.",
                              details={"field": "status"})  # fmt: skip
        o.status = data["status"]
        if o.status in ("completed", "shipped"):
            o.closed_at = datetime.now(UTC)
        if o.status not in ("accepted", "planned"):
            o.marked_for_planning = False
    if "customer_id" in data:
        await _active_customer(session, data["customer_id"])
        o.customer_id = data["customer_id"]
    if "product_id" in data:
        if await catalog.get_product(session, data["product_id"]) is None:
            raise DomainError("Choose a product.", details={"field": "product_id"})
        o.product_id = data["product_id"]
    unit_cost = data.get("unit_cost_paise")
    if unit_cost is None:
        unit_cost = int(Decimal(o.cost_paise) / o.quantity) if o.quantity else 0
    for k in ("quantity", "unit_price_paise", "processing_days", "ship_date", "priority",
              "progress_pct", "notes"):  # fmt: skip
        if k in data and (data[k] is not None or k == "notes"):
            setattr(o, k, data[k])
    # Recalculate money only when its inputs change, so editing notes or status never
    # rewrites agreed sales/cost figures.
    if {"quantity", "unit_price_paise"} & data.keys():
        o.sales_paise = _paise_mul(o.quantity, o.unit_price_paise)
    if {"quantity", "unit_cost_paise"} & data.keys():
        o.cost_paise = _paise_mul(o.quantity, unit_cost)
    if "marked_for_planning" in data and data["marked_for_planning"] is not None:
        if data["marked_for_planning"] and o.status != "accepted":
            raise DomainError("Only accepted orders can be sent to Planning. Accept it first.",
                              details={"field": "marked_for_planning"})  # fmt: skip
        o.marked_for_planning = data["marked_for_planning"]
    after = _snapshot(o)
    b, a = audit.diff(before, after)
    if a:
        await audit.record(session, actor_id=actor, action="update", entity_type="order",
                           entity_id=o.id, summary=f"Order {o.number} updated",
                           before=b, after=a)  # fmt: skip
    return await get_order(session, o.id)


async def cancel_order(
    session: AsyncSession, actor: uuid.UUID, order_id: uuid.UUID, body: OrderCancel
) -> OrderOut:
    o = await session.get(Order, order_id, with_for_update=True)
    if o is None:
        raise NotFound("Order not found.")
    if o.status not in ("new", "accepted", "planned"):
        raise DomainError(f"{o.number} is {o.status.replace('_', ' ')} and can't be cancelled.")
    before = _snapshot(o)
    o.status, o.cancel_reason, o.marked_for_planning = "cancelled", body.reason, False
    o.closed_at = datetime.now(UTC)
    await audit.record(session, actor_id=actor, action="cancel", entity_type="order", entity_id=o.id,
                       summary=f"Order {o.number} cancelled: {body.reason}",
                       before=before, after=_snapshot(o))  # fmt: skip
    return await get_order(session, o.id)


async def set_planning_selection(
    session: AsyncSession, actor: uuid.UUID, ids: list[uuid.UUID], marked: bool
) -> int:
    orders = list((await session.execute(select(Order).where(Order.id.in_(ids)))).scalars())
    if len(orders) != len(set(ids)):
        raise NotFound("One or more orders were not found.")
    bad = [o.number for o in orders if marked and o.status != "accepted"]
    if bad:
        raise DomainError("Only accepted orders can be sent to Planning: " + ", ".join(sorted(bad)),
                          details={"orders": sorted(bad)})  # fmt: skip
    for o in orders:
        if o.marked_for_planning != marked:
            o.marked_for_planning = marked
            await audit.record(session, actor_id=actor, action="update", entity_type="order",
                               entity_id=o.id, summary=f"{o.number} "
                               + ("marked for planning" if marked else "removed from planning"),
                               after={"marked_for_planning": marked})  # fmt: skip
    return len(orders)


async def reassign_customer(session: AsyncSession, source: uuid.UUID, target: uuid.UUID) -> int:
    """Used when two customer records are merged."""
    from sqlalchemy import update

    res = await session.execute(update(Order).where(Order.customer_id == source).values(customer_id=target))
    return int(res.rowcount)  # type: ignore[attr-defined]


async def find_order_for_invoice(
    session: AsyncSession, customer_id: uuid.UUID, items: list[tuple[str | None, Decimal | None]]
) -> Order | None:
    """An order of this customer whose product and quantity appear on the invoice."""
    rows = await session.execute(
        select(Order, Product.name)
        .join(Product, Product.id == Order.product_id)
        .where(Order.customer_id == customer_id, Order.status != "cancelled")
        .order_by(Order.ship_date.desc())
    )
    for o, pname in rows:
        for name, qty in items:
            if name and pname.lower() in name.lower() and qty is not None and qty == o.quantity:
                return o
    return None
