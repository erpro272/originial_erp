"""Sales statistics from saved invoices. Other modules read sales only through here."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, case, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.invoices.models import Invoice, InvoiceLine

# Units counted as "pieces" for the Units sold metric.
PIECE_UNITS = ("pcs", "pc", "nos", "no", "no.", "nos.", "piece", "pieces", "pcs.", "units", "unit")


@dataclass
class CustomerStats:
    invoices_all: int = 0
    first_date: date | None = None
    last_date: date | None = None
    lifetime_sales: int = 0
    period_sales: int = 0
    period_invoices: int = 0
    prev_sales: int = 0
    period_units: Decimal = Decimal(0)
    outstanding: int = 0


async def customer_stats(
    session: AsyncSession, p_from: date, p_to: date, prev_from: date, prev_to: date
) -> dict[uuid.UUID, CustomerStats]:
    d = Invoice.invoice_date
    total = func.coalesce(Invoice.grand_total_paise, 0)
    in_p = d.between(p_from, p_to)
    in_prev = d.between(prev_from, prev_to)
    rows = await session.execute(
        select(
            Invoice.customer_id,
            func.count(),
            func.min(d),
            func.max(d),
            func.sum(total),
            func.sum(case((in_p, total), else_=0)),
            func.count().filter(in_p),
            func.sum(case((in_prev, total), else_=0)),
            func.sum(func.coalesce(Invoice.balance_due_paise, 0)),
        ).group_by(Invoice.customer_id)
    )
    out: dict[uuid.UUID, CustomerStats] = {}
    for cid, n, first, last, life, ps, pn, prev, outst in rows:
        out[cid] = CustomerStats(n, first, last, int(life), int(ps), int(pn), int(prev),
                                 Decimal(0), int(outst))  # fmt: skip
    units = await session.execute(
        select(Invoice.customer_id, func.sum(InvoiceLine.quantity))
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .where(in_p, func.lower(func.coalesce(InvoiceLine.uom, "pcs")).in_(PIECE_UNITS))
        .group_by(Invoice.customer_id)
    )
    for cid, q in units:
        out.setdefault(cid, CustomerStats()).period_units = Decimal(q or 0)
    return out


async def customers_who_bought(session: AsyncSession, product_query: str) -> set[uuid.UUID]:
    rows = await session.execute(
        select(Invoice.customer_id)
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .where(InvoiceLine.product_name.ilike(f"%{product_query}%"))
        .distinct()
    )
    return set(rows.scalars())


async def monthly_sales(session: AsyncSession, customer_id: uuid.UUID, since: date) -> list[tuple[date, int]]:
    month = func.date_trunc("month", Invoice.invoice_date).cast(Date)
    rows = await session.execute(
        select(month, func.sum(func.coalesce(Invoice.grand_total_paise, 0)))
        .where(Invoice.customer_id == customer_id, Invoice.invoice_date >= since)
        .group_by(month)
        .order_by(month)
    )
    return [(m, int(v)) for m, v in rows]


async def top_products(
    session: AsyncSession, customer_id: uuid.UUID, limit: int = 5
) -> list[dict[str, object]]:
    rows = await session.execute(
        select(
            InvoiceLine.product_name,
            func.max(InvoiceLine.uom),
            func.sum(InvoiceLine.quantity),
            func.sum(func.coalesce(InvoiceLine.total_paise, InvoiceLine.taxable_paise, 0)),
        )
        .join(Invoice, Invoice.id == InvoiceLine.invoice_id)
        .where(Invoice.customer_id == customer_id)
        .group_by(InvoiceLine.product_name)
        .order_by(func.sum(func.coalesce(InvoiceLine.total_paise, 0)).desc())
        .limit(limit)
    )
    return [{"name": n or "—", "uom": u, "quantity": q or Decimal(0), "value_paise": int(v)}
            for n, u, q, v in rows]  # fmt: skip


async def customer_invoices(session: AsyncSession, customer_id: uuid.UUID) -> list[Invoice]:
    return list(
        (
            await session.execute(
                select(Invoice)
                .where(Invoice.customer_id == customer_id)
                .order_by(Invoice.invoice_date.desc().nulls_last(), Invoice.created_at.desc())
            )
        ).scalars()
    )


async def reassign_customer(session: AsyncSession, source: uuid.UUID, target: uuid.UUID) -> int:
    res = await session.execute(
        update(Invoice).where(Invoice.customer_id == source).values(customer_id=target)
    )
    return int(res.rowcount)  # type: ignore[attr-defined]
