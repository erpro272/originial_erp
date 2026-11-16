"""Sales statistics from saved invoices. Other modules read sales only through here."""

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import Date, case, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement

from app.invoices.models import Invoice, InvoiceLine, InvoiceReceipt

# Issued invoices only: imported / seed ones (no billing status) and Billing's issued / sent ones.
# A draft (or verified draft) is not a sale yet: it never counts in sales or what a customer owes.
ISSUED: ColumnElement[bool] = or_(
    Invoice.billing_status.is_(None), Invoice.billing_status.in_(("issued", "sent"))
)


def received_per_invoice(as_of: date | None = None):  # type: ignore[no-untyped-def]
    """Receipts (cash, advances, credit notes, opening) per invoice, up to a date: a subquery."""
    q = select(InvoiceReceipt.invoice_id.label("invoice_id"),
               func.sum(InvoiceReceipt.amount_paise).label("received")).group_by(InvoiceReceipt.invoice_id)  # fmt: skip
    if as_of is not None:
        q = q.where(InvoiceReceipt.received_on <= as_of)
    return q.subquery()


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
    rec = received_per_invoice()
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
            # what they owe = issued totals - receipts (computed, never a stored balance)
            func.sum(total - func.coalesce(rec.c.received, 0)),
        )
        .outerjoin(rec, rec.c.invoice_id == Invoice.id)
        .where(ISSUED)
        .group_by(Invoice.customer_id)
    )
    out: dict[uuid.UUID, CustomerStats] = {}
    for cid, n, first, last, life, ps, pn, prev, outst in rows:
        out[cid] = CustomerStats(n, first, last, int(life), int(ps), int(pn), int(prev),
                                 Decimal(0), int(outst))  # fmt: skip
    units = await session.execute(
        select(Invoice.customer_id, func.sum(InvoiceLine.quantity))
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .where(in_p, ISSUED, func.lower(func.coalesce(InvoiceLine.uom, "pcs")).in_(PIECE_UNITS))
        .group_by(Invoice.customer_id)
    )
    for cid, q in units:
        out.setdefault(cid, CustomerStats()).period_units = Decimal(q or 0)
    return out


async def customers_who_bought(session: AsyncSession, product_query: str) -> set[uuid.UUID]:
    rows = await session.execute(
        select(Invoice.customer_id)
        .join(InvoiceLine, InvoiceLine.invoice_id == Invoice.id)
        .where(ISSUED, InvoiceLine.product_name.ilike(f"%{product_query}%"))
        .distinct()
    )
    return set(rows.scalars())


async def monthly_sales(session: AsyncSession, customer_id: uuid.UUID, since: date) -> list[tuple[date, int]]:
    month = func.date_trunc("month", Invoice.invoice_date).cast(Date)
    rows = await session.execute(
        select(month, func.sum(func.coalesce(Invoice.grand_total_paise, 0)))
        .where(Invoice.customer_id == customer_id, Invoice.invoice_date >= since, ISSUED)
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
        .where(Invoice.customer_id == customer_id, ISSUED)
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
                .where(Invoice.customer_id == customer_id, ISSUED)
                .order_by(Invoice.invoice_date.desc().nulls_last(), Invoice.created_at.desc())
            )
        ).scalars()
    )


async def reassign_customer(session: AsyncSession, source: uuid.UUID, target: uuid.UUID) -> int:
    res = await session.execute(
        update(Invoice).where(Invoice.customer_id == source).values(customer_id=target)
    )
    return int(res.rowcount)  # type: ignore[attr-defined]


async def received_by_invoice(session: AsyncSession, invoice_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    """Invoice -> everything received on it so far (receipts, advances, credit notes, opening)."""
    if not invoice_ids:
        return {}
    rows = await session.execute(
        select(InvoiceReceipt.invoice_id, func.sum(InvoiceReceipt.amount_paise))
        .where(InvoiceReceipt.invoice_id.in_(invoice_ids))
        .group_by(InvoiceReceipt.invoice_id)
    )
    return {i: int(v) for i, v in rows.all()}
