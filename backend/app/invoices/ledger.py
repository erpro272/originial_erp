"""Issued sales invoices and what they have received: what Billing (receivables, deals) reads and writes.
Outstanding is never stored: grand total - receipts (cash, advances adjusted, credit notes, opening)."""

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.invoices.models import CASH_KINDS, Invoice, InvoiceLine, InvoiceParty, InvoiceReceipt
from app.invoices.stats import ISSUED


async def issued_invoices(session: AsyncSession, as_of: date, customer_id: uuid.UUID | None = None,
                          ids: list[uuid.UUID] | None = None) -> list[Invoice]:  # fmt: skip
    """Issued invoices dated on or before `as_of` (the receivables of that date)."""
    q = select(Invoice).where(ISSUED, Invoice.invoice_date <= as_of, Invoice.grand_total_paise > 0)
    if customer_id is not None:
        q = q.where(Invoice.customer_id == customer_id)
    if ids is not None:
        q = q.where(Invoice.id.in_(ids))
    return list((await session.execute(q.order_by(Invoice.invoice_date, Invoice.invoice_number))).scalars())


async def receipts(session: AsyncSession, invoice_ids: list[uuid.UUID], as_of: date) -> list[InvoiceReceipt]:
    if not invoice_ids:
        return []
    q = (select(InvoiceReceipt).where(InvoiceReceipt.invoice_id.in_(invoice_ids), InvoiceReceipt.received_on <= as_of)
         .order_by(InvoiceReceipt.received_on, InvoiceReceipt.created_at))  # fmt: skip
    return list((await session.execute(q)).scalars())


async def cash_received(session: AsyncSession, start: date, end: date) -> tuple[int, int]:
    """(amount, count) of real money received in the period (advances adjusted / credit notes are not cash)."""
    q = select(func.coalesce(func.sum(InvoiceReceipt.amount_paise), 0), func.count()).where(
        and_(InvoiceReceipt.kind.in_(CASH_KINDS), InvoiceReceipt.received_on.between(start, end))
    )
    total, n = (await session.execute(q)).one()
    return int(total), int(n)


async def add_receipt(session: AsyncSession, actor: uuid.UUID, invoice: Invoice, kind: str, amount_paise: int,
                      received_on: date, method: str | None, reference: str | None,
                      note: str | None) -> InvoiceReceipt:  # fmt: skip
    r = InvoiceReceipt(invoice_id=invoice.id, kind=kind, amount_paise=amount_paise, received_on=received_on,
                       method=method, reference=reference, note=note, actor_id=actor)  # fmt: skip
    session.add(r)
    await session.flush()
    return r


async def get_invoice(session: AsyncSession, invoice_id: uuid.UUID, lock: bool = False) -> Invoice | None:
    return await session.get(Invoice, invoice_id, with_for_update=lock)


async def deal_invoices(session: AsyncSession, deal_ids: list[uuid.UUID]) -> list[Invoice]:
    """Billing's sales invoices (any status) of these deals."""
    if not deal_ids:
        return []
    q = select(Invoice).where(Invoice.deal_id.in_(deal_ids)).order_by(Invoice.created_at)
    return list((await session.execute(q)).scalars())


async def invoices_of_orders(session: AsyncSession, order_ids: list[uuid.UUID]) -> list[Invoice]:
    """Issued invoices recorded against these orders (imported ones carry the order, not a deal)."""
    if not order_ids:
        return []
    q = select(Invoice).where(Invoice.order_id.in_(order_ids), ISSUED)
    return list((await session.execute(q)).scalars())


async def issued_between(session: AsyncSession, start: date, end: date) -> int:
    q = select(func.count()).where(ISSUED, Invoice.invoice_date.between(start, end))
    return int((await session.execute(q)).scalar_one())


# ---- Billing's own sales invoices (draft -> verified -> issued -> sent) -----------------------------


def _amounts(qty: Decimal, rate: int, other: int, intra: bool) -> dict[str, int]:
    from decimal import ROUND_HALF_UP

    taxable = int((qty * rate).quantize(Decimal(1), ROUND_HALF_UP)) + other
    if intra:  # CGST 9% + SGST 9%
        cg = sg = int((Decimal(taxable) * Decimal("0.09")).quantize(Decimal(1), ROUND_HALF_UP))
        ig = 0
    else:  # IGST 18%
        cg = sg = 0
        ig = int((Decimal(taxable) * Decimal("0.18")).quantize(Decimal(1), ROUND_HALF_UP))
    gross = taxable + cg + sg + ig
    grand = int((Decimal(gross) / 100).quantize(Decimal(1), ROUND_HALF_UP)) * 100  # rounded to the rupee
    return {
        "taxable": taxable,
        "cgst": cg,
        "sgst": sg,
        "igst": ig,
        "round_off": grand - gross,
        "grand": grand,
    }


async def create_draft(session: AsyncSession, *, deal_id: uuid.UUID, customer_id: uuid.UUID, order_id: uuid.UUID | None,
                       product_id: uuid.UUID | None, product_name: str, qty: Decimal, unit: str, rate: int,
                       terms_days: int, seller: dict[str, str | None], buyer: dict[str, str | None]) -> Invoice:  # fmt: skip
    """A draft sales invoice: not a receivable, no number, editable until issued."""
    intra = (seller.get("state_code") or "") == (buyer.get("state_code") or "")
    inv = Invoice(source="billing", billing_status="draft", deal_id=deal_id, customer_id=customer_id, order_id=order_id,
                  invoice_type="tax_invoice", seller_gstin=seller.get("gstin"), buyer_gstin=buyer.get("gstin"),
                  place_of_supply_code=buyer.get("state_code"), supply_type="intra" if intra else "inter",
                  payment_terms_days=terms_days, total_quantity=qty)  # fmt: skip
    session.add(inv)
    await session.flush()
    session.add(InvoiceLine(invoice_id=inv.id, line_no=1, product_id=product_id, product_name=product_name,
                            quantity=qty, uom=unit.upper(), unit_price_paise=rate, gst_rate=Decimal(18)))  # fmt: skip
    for role, p in (("seller", seller), ("buyer", buyer)):
        session.add(InvoiceParty(invoice_id=inv.id, role=role, name=p.get("name"), gstin=p.get("gstin"),
                                 state_code=p.get("state_code")))  # fmt: skip
    await session.flush()
    await set_amounts(session, inv, qty, rate, 0, terms_days)
    return inv


async def line_of(session: AsyncSession, inv: Invoice) -> InvoiceLine:
    q = select(InvoiceLine).where(InvoiceLine.invoice_id == inv.id).order_by(InvoiceLine.line_no)
    return (await session.execute(q)).scalars().first()  # type: ignore[return-value]


async def set_amounts(
    session: AsyncSession, inv: Invoice, qty: Decimal, rate: int, other: int, terms_days: int
) -> None:
    """Recalculate a draft from quantity x rate (+ other charges) and the GST of the supply."""
    a = _amounts(qty, rate, other, inv.supply_type == "intra")
    ln = await line_of(session, inv)
    ln.quantity, ln.unit_price_paise, ln.taxable_paise = qty, rate, a["taxable"] - other
    ln.cgst_paise, ln.sgst_paise, ln.igst_paise = a["cgst"] or None, a["sgst"] or None, a["igst"] or None
    ln.total_paise = a["taxable"] - other + a["cgst"] + a["sgst"] + a["igst"]
    inv.total_quantity, inv.other_charges_paise, inv.payment_terms_days = qty, other or None, terms_days
    inv.subtotal_paise = inv.total_taxable_paise = a["taxable"]
    inv.total_cgst_paise, inv.total_sgst_paise = a["cgst"] or None, a["sgst"] or None
    inv.total_igst_paise, inv.round_off_paise, inv.grand_total_paise = (
        a["igst"] or None,
        a["round_off"],
        a["grand"],
    )
    await session.flush()


async def next_number(session: AsyncSession, prefix: str, fy: str) -> str:
    """The next invoice number of the series (DMC/26-27/0042): continues after the highest one already used."""
    from app.core import counters

    like = f"{prefix}/{fy}/%"
    used = (
        await session.execute(select(Invoice.invoice_number).where(Invoice.invoice_number.like(like)))
    ).scalars()
    top = max((int(n.rsplit("/", 1)[1]) for n in used if n and n.rsplit("/", 1)[1].isdigit()), default=0)
    name = f"invoice-{prefix}-{fy}"
    await counters.ensure_at_least(session, name, top)
    return f"{prefix}/{fy}/{await counters.next_value(session, name, start=top):04d}"


async def series_prefix(session: AsyncSession) -> str | None:
    """The prefix of the latest issued invoice numbered PREFIX/FY/NNNN, to continue the same series."""
    q = (select(Invoice.invoice_number).where(ISSUED, Invoice.invoice_number.like("%/%/%"))
         .order_by(Invoice.invoice_date.desc().nulls_last()).limit(20))  # fmt: skip
    for n in (await session.execute(q)).scalars():
        parts = (n or "").split("/")
        if len(parts) == 3 and parts[2].isdigit() and parts[0]:
            return parts[0]
    return None


async def monthly_totals(session: AsyncSession, start: date, end: date) -> dict[str, dict[str, int]]:
    """Per month ("2026-06"): issued invoice value by invoice date, and real money received by receipt date
    (each rupee counted once: a receipt is counted in the month it arrived, never again as invoiced)."""
    month = func.to_char(Invoice.invoice_date, "YYYY-MM")
    inv = (await session.execute(
        select(month, func.sum(Invoice.grand_total_paise)).where(ISSUED, Invoice.invoice_date.between(start, end))
        .group_by(month)
    )).all()  # fmt: skip
    rmonth = func.to_char(InvoiceReceipt.received_on, "YYYY-MM")
    got = (await session.execute(
        select(rmonth, func.sum(InvoiceReceipt.amount_paise))
        .where(InvoiceReceipt.kind.in_(CASH_KINDS), InvoiceReceipt.received_on.between(start, end)).group_by(rmonth)
    )).all()  # fmt: skip
    out: dict[str, dict[str, int]] = {}
    for m, v in inv:
        out.setdefault(m, {})["invoiced"] = int(v or 0)
    for m, v in got:
        out.setdefault(m, {})["collected"] = int(v or 0)
    return out
