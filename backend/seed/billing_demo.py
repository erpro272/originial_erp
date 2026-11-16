"""Billing demo (dev seed only): promises and follow-ups on overdue receivables, and supplier invoices at every
approval stage on the received demo POs. Inserted directly (the seed role bypasses RLS: everything is filtered by
`tenant_id`). Deals are created by the app on first read. Idempotent: skipped when supplier invoices exist."""

import uuid
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Interaction, PayableEvent, PaymentPromise, SupplierInvoice, SupplierPayment
from app.core import clock
from app.core.db import set_tenant
from app.invoices.models import Invoice, InvoiceReceipt
from app.purchasing.models import PurchaseOrder, PurchaseOrderLine
from seed.purchase_demo import SOURCE

# the received demo POs, newest first, get these stages (the rest are paid in full)
STAGES = ["pending_verif_mismatch", "pending_verif", "pending_owner", "pending_owner", "approved", "scheduled",
          "on_hold", "rejected"]  # fmt: skip
NOTES = [
    ("call", "Called accounts: payment run is on Friday, they will include us."),
    ("whatsapp", "Customer asked for the delivery challan copy before releasing payment."),
    ("email", "Sent the statement of account with all open invoices."),
    ("visit", "Met the purchase manager; asked to split the payment over two weeks."),
]


def _ev(
    inv: SupplierInvoice, action: str, frm: str | None, to: str | None, at: datetime, note: str | None = None
) -> PayableEvent:
    return PayableEvent(
        supplier_invoice_id=inv.id, action=action, from_status=frm, to_status=to, note=note, created_at=at
    )


async def seed_billing(s: AsyncSession, tenant_id: uuid.UUID) -> int:
    await set_tenant(s, tenant_id)
    if (await s.execute(select(SupplierInvoice.id).where(SupplierInvoice.tenant_id == tenant_id))).first():
        return 0
    today, now = clock.today(), datetime.now(UTC)

    # ---- receivables: promises and follow-ups on the biggest overdue invoices
    got = (select(InvoiceReceipt.invoice_id, func.sum(InvoiceReceipt.amount_paise).label("paid"))
           .where(InvoiceReceipt.tenant_id == tenant_id).group_by(InvoiceReceipt.invoice_id).subquery())  # fmt: skip
    rows = (await s.execute(
        select(Invoice, func.coalesce(got.c.paid, 0)).outerjoin(got, got.c.invoice_id == Invoice.id)
        .where(Invoice.tenant_id == tenant_id, Invoice.due_date < today,
               Invoice.grand_total_paise - func.coalesce(got.c.paid, 0) > 0)
        .order_by((Invoice.grand_total_paise - func.coalesce(got.c.paid, 0)).desc()).limit(12)
    )).all()  # fmt: skip
    seen: set[uuid.UUID] = set()
    k = 0
    for inv, paid in rows:
        if inv.customer_id in seen:
            continue
        seen.add(inv.customer_id)
        owed = (inv.grand_total_paise or 0) - int(paid)
        channel, text = NOTES[k % len(NOTES)]
        s.add(Interaction(customer_id=inv.customer_id, invoice_id=inv.id, channel=channel,
                          direction="incoming" if channel == "whatsapp" else "outgoing", summary=text,
                          next_follow_up=today + timedelta(days=3 + k), created_at=now - timedelta(days=2 + k)))  # fmt: skip
        if k % 2 == 0:  # a promise, then a later one: both kept
            first = (owed // 2 // 100) * 100
            s.add(PaymentPromise(invoice_id=inv.id, amount_paise=first, promised_on=today - timedelta(days=4),
                                 note="Part payment promised", created_at=now - timedelta(days=12)))  # fmt: skip
            s.add(PaymentPromise(invoice_id=inv.id, amount_paise=first, promised_on=today + timedelta(days=5 + k),
                                 note="Missed the first date; new commitment", created_at=now - timedelta(days=1)))  # fmt: skip
        k += 1
        if k >= 6:
            break

    # ---- payables: one supplier invoice per received demo PO
    pos = (await s.execute(
        select(PurchaseOrder, PurchaseOrderLine).join(PurchaseOrderLine, PurchaseOrderLine.po_id == PurchaseOrder.id)
        .where(PurchaseOrder.tenant_id == tenant_id, PurchaseOrder.source == SOURCE, PurchaseOrder.status == "received")
        .order_by(PurchaseOrder.approved_at.desc())
    )).all()  # fmt: skip
    n = 0
    for i, (po, ln) in enumerate(pos):
        stage = STAGES[i] if i < len(STAGES) else "paid"
        assert po.approved_at is not None
        arrived = po.approved_at + timedelta(days=4)
        inv_date = arrived.date() + timedelta(days=1)
        qty = ln.received_qty + (Decimal("0.2") if stage == "pending_verif_mismatch" else 0)
        taxable = int((qty * ln.price_per_unit_paise).quantize(Decimal(1), ROUND_HALF_UP))
        gst = int((Decimal(taxable) * Decimal("0.18")).quantize(Decimal(1), ROUND_HALF_UP))
        status = {"pending_verif_mismatch": "pending_verif"}.get(stage, stage)
        inv = SupplierInvoice(supplier_id=po.supplier_id, po_id=po.id, number=f"SI/{inv_date:%y%m}/{po.number[3:]}",
                              invoice_date=inv_date, due_date=inv_date + timedelta(days=30), quantity=qty,
                              rate_paise=ln.price_per_unit_paise, taxable_paise=taxable, gst_paise=gst,
                              total_paise=taxable + gst, status=status, match={},
                              hold_reason={"on_hold": "Quality complaint on the last lot",
                                           "rejected": "Rate differs from the PO"}.get(stage),
                              created_at=datetime.combine(inv_date, datetime.min.time(), UTC))  # fmt: skip
        s.add(inv)
        await s.flush()
        t0 = inv.created_at
        s.add(_ev(inv, "Invoice received", None, "pending_verif", t0))
        if status in ("pending_owner", "approved", "scheduled", "paid", "on_hold", "rejected"):
            s.add(
                _ev(
                    inv,
                    "Verified by accounts",
                    "pending_verif",
                    "pending_owner",
                    t0 + timedelta(days=1),
                    "Three-way match agrees",
                )
            )
        if status in ("approved", "scheduled", "paid"):
            s.add(_ev(inv, "Approved by owner", "pending_owner", "approved", t0 + timedelta(days=2)))
        if status == "scheduled":
            s.add(SupplierPayment(supplier_invoice_id=inv.id, amount_paise=inv.total_paise,
                                  scheduled_for=today + timedelta(days=2), status="scheduled"))  # fmt: skip
            s.add(_ev(inv, "Payment scheduled", "approved", "scheduled", now - timedelta(days=1)))
        if status == "paid":
            on = min(today, inv.due_date - timedelta(days=2))
            s.add(SupplierPayment(supplier_invoice_id=inv.id, amount_paise=inv.total_paise, scheduled_for=on,
                                  status="confirmed", utr=f"UTR{po.number[3:]}{inv_date:%m%d}", executed_on=on,
                                  confirmed_on=on))  # fmt: skip
            s.add(_ev(inv, "Payment scheduled", "approved", "scheduled", t0 + timedelta(days=3)))
            s.add(
                _ev(
                    inv, "Bank confirmed", "scheduled", "paid", datetime.combine(on, datetime.min.time(), UTC)
                )
            )
        if status in ("on_hold", "rejected"):
            s.add(_ev(inv, "Put on hold" if status == "on_hold" else "Rejected", "pending_owner", status,
                      t0 + timedelta(days=2), inv.hold_reason))  # fmt: skip
        n += 1
    await s.flush()
    return n
