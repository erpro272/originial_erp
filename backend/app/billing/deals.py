"""Deals: the TXN-#### spine of every sale and purchase.

Every order gets a sale deal and every PO a purchase deal (created on first read, idempotent; one per order / PO
by a unique constraint). A deal can also start from an enquiry (provisional, no order yet).

Status is derived from the linked records, never typed: see `_sale_status` / `_purchase_status`. Documents and
activity are views of the records that own them (order, PO, gate entries and QC, sales invoice and receipts,
supplier invoice and payments), plus Billing's own deal events and interactions; nothing is copied.

Sales invoices: draft (from the shipped order: an order marked Shipped counts as fully dispatched until Production
records dispatches) -> verified (accounts) -> issued (owner or accountant: number, lock, receivable, all in one
transaction) -> sent. An issued invoice is never edited.
"""

import uuid
from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Deal, DealEvent, Interaction, SupplierInvoice, SupplierPayment
from app.billing.receivables import _names, inr, interactions_for, period
from app.billing.schemas import (
    ActivityOut,
    DealCreateIn,
    DealDetail,
    DealEditIn,
    DealKpis,
    DealRow,
    DealsOut,
    DocumentOut,
    DraftEditIn,
    InteractionIn,
    InteractionOut,
    InvoiceCard,
    SendIn,
)
from app.core import audit, clock, counters, events
from app.core.errors import Conflict, DomainError, NotFound
from app.core.gst import financial_year
from app.core.models import AuditLog, Tenant
from app.core.services import kv
from app.customers import service as customers
from app.invoices import ledger
from app.invoices.models import Invoice, InvoiceReceipt
from app.orders import service as orders
from app.purchasing import service as purchasing

ORDER_LABEL = {"new": "Received", "accepted": "Accepted", "planned": "Planned", "in_production": "In production",
               "completed": "Made", "shipped": "Shipped", "cancelled": "Cancelled"}  # fmt: skip
PO_LABEL = {"awaiting_approval": "Awaiting approval", "ordered": "Sent", "confirmed": "Confirmed",
            "dispatched": "In transit", "at_gate": "At the gate", "received": "Received", "cancelled": "Cancelled"}  # fmt: skip
AP_LABEL = {"pending_verif": "Awaiting review", "pending_owner": "Verified", "approved": "Approved",
            "scheduled": "Payment scheduled", "paid": "Paid", "on_hold": "On hold", "rejected": "Rejected"}  # fmt: skip
CLOSED = ("Completed", "Cancelled")


# ---- making sure every order and PO has its deal ------------------------------------------------------


async def _next_number(session: AsyncSession) -> str:
    return f"TXN-{await counters.next_value(session, 'deal', start=1000)}"


async def ensure_deals(session: AsyncSession) -> None:
    """Orders and POs without a deal get one (idempotent)."""
    have_o = set((await session.execute(select(Deal.order_id).where(Deal.order_id.is_not(None)))).scalars())
    have_p = set((await session.execute(select(Deal.po_id).where(Deal.po_id.is_not(None)))).scalars())
    of = await orders.facts(session)
    new_orders = sorted((o for oid, o in of.items() if oid not in have_o), key=lambda o: o["created_at"])
    for o in new_orders:
        session.add(Deal(number=await _next_number(session), kind="sale", name=f"{o['product']} – {o['number']}",
                         order_id=o["id"], customer_id=o["customer_id"], reference=o["number"], reference_kind="order",
                         item=o["product"], quantity=o["quantity"], unit=o["unit"]))  # fmt: skip
    po_ids = [i for i in await purchasing.all_po_ids(session) if i not in have_p]
    pf = await purchasing.po_facts(session, po_ids)
    for p in sorted(pf.values(), key=lambda p: p["created_at"]):
        session.add(Deal(number=await _next_number(session), kind="purchase",
                         name=f"{p['material']} ({p['code']}) – {p['number']}", po_id=p["id"],
                         supplier_id=p["supplier_id"], reference=p["number"], reference_kind="po", item=p["material"],
                         quantity=p["quantity"], unit=p["unit"], payment_terms_days=30))  # fmt: skip
    if new_orders or pf:
        await session.flush()


async def deal_for_po(session: AsyncSession, po_id: uuid.UUID) -> Deal | None:
    await ensure_deals(session)
    return (await session.execute(select(Deal).where(Deal.po_id == po_id))).scalar_one_or_none()


# ---- everything a deal links to, loaded in bulk ---------------------------------------------------------


class _Bundle:
    def __init__(self) -> None:
        self.orders: dict[uuid.UUID, dict[str, Any]] = {}
        self.pos: dict[uuid.UUID, dict[str, Any]] = {}
        self.invoices: dict[uuid.UUID, list[Invoice]] = defaultdict(list)  # deal -> sales invoices
        self.receipts: dict[uuid.UUID, list[InvoiceReceipt]] = defaultdict(list)  # invoice -> receipts
        self.sinv: dict[uuid.UUID, list[SupplierInvoice]] = defaultdict(list)  # deal -> supplier invoices
        self.spay: dict[uuid.UUID, list[SupplierPayment]] = defaultdict(list)  # supplier invoice -> payments
        self.events: dict[uuid.UUID, list[DealEvent]] = defaultdict(list)
        self.interactions: dict[uuid.UUID, list[Interaction]] = defaultdict(list)
        self.companies: dict[uuid.UUID, str] = {}


async def _bundle(session: AsyncSession, deals: list[Deal]) -> _Bundle:
    b = _Bundle()
    ids = [d.id for d in deals]
    b.orders = await orders.facts(session, [d.order_id for d in deals if d.order_id])
    b.pos = await purchasing.po_facts(session, [d.po_id for d in deals if d.po_id])
    by_order = {d.order_id: d.id for d in deals if d.order_id}
    invs = await ledger.deal_invoices(session, ids)
    legacy = [i for i in await ledger.invoices_of_orders(session, list(by_order)) if not i.deal_id]
    for i in invs:
        assert i.deal_id is not None
        b.invoices[i.deal_id].append(i)
    for i in legacy:
        b.invoices[by_order[i.order_id]].append(i)  # type: ignore[index]
    issued = [i.id for v in b.invoices.values() for i in v if i.billing_status in (None, "issued", "sent")]
    for r in await ledger.receipts(session, issued, clock.today()):
        b.receipts[r.invoice_id].append(r)
    if ids:
        for s in (
            await session.execute(select(SupplierInvoice).where(SupplierInvoice.deal_id.in_(ids)))
        ).scalars():
            assert s.deal_id is not None
            b.sinv[s.deal_id].append(s)
        sids = [s.id for v in b.sinv.values() for s in v]
        if sids:
            for p in (await session.execute(select(SupplierPayment).where(
                    SupplierPayment.supplier_invoice_id.in_(sids)))).scalars():  # fmt: skip
                b.spay[p.supplier_invoice_id].append(p)
        for e in (await session.execute(select(DealEvent).where(DealEvent.deal_id.in_(ids))
                                        .order_by(DealEvent.created_at))).scalars():  # fmt: skip
            b.events[e.deal_id].append(e)
        for it in (await session.execute(select(Interaction).where(Interaction.deal_id.in_(ids)))).scalars():
            assert it.deal_id is not None
            b.interactions[it.deal_id].append(it)
    cust = await customers.briefs(session, list({d.customer_id for d in deals if d.customer_id}))
    b.companies = {k: v["name"] for k, v in cust.items()}
    b.companies.update(
        await purchasing.supplier_names(session, list({d.supplier_id for d in deals if d.supplier_id}))
    )
    return b


def _issued(invs: list[Invoice]) -> list[Invoice]:
    return [i for i in invs if i.billing_status in (None, "issued", "sent")]


def _sale_status(d: Deal, b: _Bundle) -> str:
    o = b.orders.get(d.order_id) if d.order_id else None
    if d.cancelled_reason or (o and o["status"] == "cancelled"):
        return "Cancelled"
    if d.on_hold:
        return "On Hold"
    if o is None:
        return "Enquiry Received"
    invs = b.invoices.get(d.id, [])
    issued = _issued(invs)
    if issued:
        total = sum(i.grand_total_paise or 0 for i in issued)
        got = sum(r.amount_paise for i in issued for r in b.receipts.get(i.id, []))
        if got >= total and o["status"] == "shipped":
            return "Completed"  # fully dispatched AND fully paid
        return "Partially Settled" if got > 0 else "Invoiced"
    if invs:
        return "Invoice Pending"
    return {"shipped": "Dispatched", "completed": "Processing", "in_production": "Processing",
            "new": "Awaiting Response"}.get(o["status"], "Order Confirmed")  # fmt: skip


def _purchase_status(d: Deal, b: _Bundle) -> str:
    p = b.pos.get(d.po_id) if d.po_id else None
    if d.cancelled_reason or (p and p["status"] == "cancelled"):
        return "Cancelled"
    sinv = b.sinv.get(d.id, [])
    if d.on_hold or any(s.status in ("on_hold", "rejected") for s in sinv):
        return "On Hold"
    if p is None:
        return "Enquiry Received"
    if sinv:
        total = sum(s.total_paise for s in sinv)
        paid = sum(x.amount_paise for s in sinv for x in b.spay.get(s.id, []) if x.status == "confirmed")
        if paid >= total and p["status"] == "received":
            return "Completed"
        if paid > 0:
            return "Partially Settled"
        if any(s.status == "pending_verif" for s in sinv):
            return "Invoice Pending"
        return "Invoiced"
    if p["status"] == "received":
        return "Invoice Pending"  # goods in: the supplier's invoice is awaited
    if Decimal(p["received_qty"]) > 0:
        return "Partially Dispatched"
    return {"awaiting_approval": "Awaiting Response", "dispatched": "Dispatched", "at_gate": "Dispatched"}.get(
        p["status"], "Order Confirmed")  # fmt: skip


def _status(d: Deal, b: _Bundle) -> str:
    return _sale_status(d, b) if d.kind == "sale" else _purchase_status(d, b)


def _value(d: Deal, b: _Bundle) -> int | None:
    if d.kind == "sale":
        issued = _issued(b.invoices.get(d.id, []))
        if issued:
            return sum(i.grand_total_paise or 0 for i in issued)
        o = b.orders.get(d.order_id) if d.order_id else None
        return o["sales_paise"] if o else d.expected_value_paise
    p = b.pos.get(d.po_id) if d.po_id else None
    return p["value_paise"] if p else d.expected_value_paise


def _documents(d: Deal, b: _Bundle) -> list[DocumentOut]:
    docs: list[DocumentOut] = []
    if d.kind == "sale":
        o = b.orders.get(d.order_id) if d.order_id else None
        if o:
            docs.append(DocumentOut(key=f"order:{o['id']}", kind="customer_po", name="Customer PO / sales order",
                                    number=o["number"], direction="incoming", status=ORDER_LABEL.get(o["status"], o["status"]),
                                    date=o["created_at"].date(), amount_paise=o["sales_paise"], source="Orders"))  # fmt: skip
        for i in b.invoices.get(d.id, []):
            st = (i.billing_status or "issued").capitalize()
            docs.append(DocumentOut(key=f"invoice:{i.id}", kind="sales_invoice", name="Tax invoice",
                                    number=i.invoice_number, direction="outgoing" if i.billing_status != "draft" else "internal",
                                    status=st, date=i.invoice_date, amount_paise=i.grand_total_paise,
                                    source="Invoice / E-bill"))  # fmt: skip
            for r in b.receipts.get(i.id, []):
                name = {"receipt": "Payment receipt", "advance": "Advance adjusted", "credit_note": "Credit note",
                        "opening": "Payment (before Billing)"}[r.kind]  # fmt: skip
                docs.append(DocumentOut(key=f"receipt:{r.id}", kind="receipt", name=name, number=r.reference,
                                        direction="incoming", status="Received", date=r.received_on,
                                        amount_paise=r.amount_paise, source="Payments"))  # fmt: skip
    else:
        p = b.pos.get(d.po_id) if d.po_id else None
        if p:
            docs.append(DocumentOut(key=f"po:{p['id']}", kind="purchase_order", name="Purchase order", number=p["number"],
                                    direction="outgoing", status=PO_LABEL.get(p["status"], p["status"]),
                                    date=p["created_at"].date(), amount_paise=p["value_paise"], source="Purchasing"))  # fmt: skip
            for k, e in enumerate(p["events"]):
                if e["kind"] in ("gate_entry", "qc"):
                    docs.append(DocumentOut(key=f"po_event:{p['id']}:{k}", kind="grn" if e["kind"] == "gate_entry" else "qc",
                                            name="Goods receipt (gate entry)" if e["kind"] == "gate_entry" else "QC report",
                                            number=e["data"].get("ref"), direction="internal", status="Recorded",
                                            date=e["at"].date(), amount_paise=None, source="Purchasing"))  # fmt: skip
        for s in b.sinv.get(d.id, []):
            docs.append(DocumentOut(key=f"supplier_invoice:{s.id}", kind="supplier_invoice", name="Supplier invoice",
                                    number=s.number, direction="incoming", status=AP_LABEL.get(s.status, s.status),
                                    date=s.invoice_date, amount_paise=s.total_paise, source="Payments"))  # fmt: skip
            for x in b.spay.get(s.id, []):
                if x.status in ("executed", "confirmed"):
                    docs.append(DocumentOut(key=f"payment:{x.id}", kind="payment_advice", name="Payment advice",
                                            number=x.utr, direction="outgoing",
                                            status="Bank confirmed" if x.status == "confirmed" else "Sent",
                                            date=x.executed_on, amount_paise=x.amount_paise, source="Payments"))  # fmt: skip
    return docs


def _at(d: date | datetime) -> datetime:
    return d if isinstance(d, datetime) else datetime(d.year, d.month, d.day, 12, tzinfo=UTC)


async def _activity(
    session: AsyncSession, d: Deal, b: _Bundle, names: dict[uuid.UUID, str]
) -> list[ActivityOut]:
    out: list[ActivityOut] = []
    if d.kind == "sale" and d.order_id and d.order_id in b.orders:
        o = b.orders[d.order_id]
        out.append(ActivityOut(at=o["created_at"], title=f"Order {o['number']} received in Orders", direction="incoming",
                               source="Orders", by=None, milestone=True, document_key=f"order:{o['id']}"))  # fmt: skip
        rows = (await session.execute(select(AuditLog).where(AuditLog.entity_type == "order",
                                                             AuditLog.entity_id == str(o["id"]), AuditLog.action == "update")
                                      .order_by(AuditLog.at))).scalars()  # fmt: skip
        for a in rows:
            out.append(ActivityOut(at=a.at, title=a.summary or "Order updated", direction="internal",
                                   source="Orders", by=a.actor_name, milestone="shipped" in (a.summary or "").lower(),
                                   document_key=None))  # fmt: skip
        for i in b.invoices.get(d.id, []):
            for r in b.receipts.get(i.id, []):
                out.append(ActivityOut(at=_at(r.received_on), title=f"Payment received {inr(r.amount_paise)}"
                                       + (f" · {r.reference}" if r.reference else ""), direction="incoming",
                                       source="Receivables", by=names.get(r.actor_id) if r.actor_id else None,
                                       milestone=True, document_key=f"receipt:{r.id}"))  # fmt: skip
    if d.kind == "purchase" and d.po_id and d.po_id in b.pos:
        p = b.pos[d.po_id]
        for e in p["events"]:
            out.append(ActivityOut(at=e["at"], title=f"{p['number']}: {e['summary']}",
                                   direction="outgoing" if e["kind"] in ("approved",) else
                                   "incoming" if e["kind"] in ("confirmed", "dispatched") else "internal",
                                   source="Purchasing", by=names.get(e["actor_id"]) if e["actor_id"] else None,
                                   milestone=e["kind"] in ("raised", "approved", "gate_entry", "qc"), document_key=None))  # fmt: skip
        for s in b.sinv.get(d.id, []):
            out.append(ActivityOut(at=s.created_at, title=f"Supplier invoice {s.number} received", direction="incoming",
                                   source="Payables", by=None, milestone=True, document_key=f"supplier_invoice:{s.id}"))  # fmt: skip
            for x in b.spay.get(s.id, []):
                if x.executed_on:
                    out.append(ActivityOut(at=_at(x.executed_on), title=f"Payment sent {inr(x.amount_paise)} · UTR {x.utr}",
                                           direction="outgoing", source="Payables", by=None, milestone=True,
                                           document_key=f"payment:{x.id}"))  # fmt: skip
                if x.confirmed_on:
                    out.append(ActivityOut(at=_at(x.confirmed_on), title=f"Bank confirmed {inr(x.amount_paise)}",
                                           direction="internal", source="Bank", by=None, milestone=False, document_key=None))  # fmt: skip
    for e in b.events.get(d.id, []):
        out.append(ActivityOut(at=e.created_at, title=e.summary, direction=e.direction,
                               source="Invoice / E-bill", by=names.get(e.actor_id) if e.actor_id else None,
                               milestone=e.milestone, document_key=e.data.get("document_key") if e.data else None))  # fmt: skip
    for it in b.interactions.get(d.id, []):
        out.append(ActivityOut(at=it.created_at, title=f"{it.channel.capitalize()}: {it.summary}",
                               direction=it.direction, source="Interactions",
                               by=names.get(it.actor_id) if it.actor_id else None, milestone=False, document_key=None))  # fmt: skip
    out.sort(key=lambda a: a.at, reverse=True)
    return out


def _row(d: Deal, b: _Bundle, latest: ActivityOut | None) -> DealRow:
    return DealRow(id=d.id, number=d.number, kind=d.kind, name=d.name, reference=d.reference,
                   company_id=d.customer_id or d.supplier_id,
                   company=b.companies.get(d.customer_id or d.supplier_id, "") if (d.customer_id or d.supplier_id) else "",  # type: ignore[arg-type]
                   documents=len(_documents(d, b)), latest_activity=latest.title if latest else None,
                   latest_at=latest.at if latest else None, latest_direction=latest.direction if latest else None,
                   value_paise=_value(d, b), status=d.status, provisional=d.provisional,
                   archived=d.archived_at is not None)  # fmt: skip


async def _refresh(session: AsyncSession, deals: list[Deal], b: _Bundle) -> None:
    """Store the derived status (so lists can filter on it); log a change as a deal event."""
    for d in deals:
        st = _status(d, b)
        if st != d.status:
            if d.status and d.created_at is not None and b.events is not None:
                session.add(DealEvent(deal_id=d.id, kind="status", summary=f"Deal status: {d.status} → {st}",
                                      direction="internal", data={"from": d.status, "to": st}))  # fmt: skip
            d.status = st
    await session.flush()


async def refresh_status(session: AsyncSession, deal_id: uuid.UUID) -> None:
    d = await session.get(Deal, deal_id)
    if d is not None:
        await _refresh(session, [d], await _bundle(session, [d]))


# ---- list + KPIs ----------------------------------------------------------------------------------------


async def list_deals(session: AsyncSession, month: str | None = None) -> DealsOut:
    await ensure_deals(session)
    deals = list((await session.execute(select(Deal).order_by(Deal.created_at.desc()))).scalars())
    b = await _bundle(session, deals)
    await _refresh(session, deals, b)
    names: dict[uuid.UUID, str] = {}
    rows = []
    start = end = None
    if month and month != "all":
        p = period(month)
        start, end = p.start, p.as_of
    docs_in = 0
    invoices = 0
    for d in deals:
        acts = await _activity(session, d, b, names) if d.kind == "purchase" else _cheap_activity(d, b)
        if (
            start
            and end
            and not (start <= d.created_at.date() <= end)
            and not any(start <= a.at.date() <= end for a in acts)
        ):
            continue
        rows.append(_row(d, b, acts[0] if acts else None))
        docs = _documents(d, b)
        docs_in += sum(1 for x in docs if x.direction == "incoming" and _in(x.date, start, end))
        invoices += sum(1 for i in _issued(b.invoices.get(d.id, [])) if _in(i.invoice_date, start, end))
    live = [r for r in rows if r.status not in CLOSED and not r.archived]
    kpis = DealKpis(active=len(live), total=len(rows),
                    awaiting_response=sum(r.status in ("Awaiting Response", "Negotiation") for r in live),
                    documents_received=docs_in, invoices_issued=invoices)  # fmt: skip
    rows.sort(key=lambda r: r.latest_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    return DealsOut(kpis=kpis, rows=rows, companies=sorted({r.company for r in rows if r.company}),
                    statuses=sorted({r.status for r in rows}))  # fmt: skip


def _in(d: date | None, start: date | None, end: date | None) -> bool:
    """In the selected month (always, when no month is selected)."""
    if start is None or end is None:
        return True
    return d is not None and start <= d <= end


def _cheap_activity(d: Deal, b: _Bundle) -> list[ActivityOut]:
    """Latest activity for the list without reading the audit log of every order (the drawer has it all)."""
    out: list[ActivityOut] = []
    o = b.orders.get(d.order_id) if d.order_id else None
    if o:
        out.append(ActivityOut(at=o["created_at"], title=f"Order {o['number']} received in Orders",
                               direction="incoming", source="Orders", by=None, milestone=True, document_key=None))  # fmt: skip
        if o.get("closed_at"):
            out.append(ActivityOut(at=o["closed_at"], title=f"Order {ORDER_LABEL.get(o['status'], o['status']).lower()}",
                                   direction="internal", source="Orders", by=None, milestone=True, document_key=None))  # fmt: skip
    for i in b.invoices.get(d.id, []):
        for r in b.receipts.get(i.id, []):
            out.append(ActivityOut(at=_at(r.received_on), title=f"Payment received {inr(r.amount_paise)}",
                                   direction="incoming", source="Receivables", by=None, milestone=True, document_key=None))  # fmt: skip
    for e in b.events.get(d.id, []):
        out.append(ActivityOut(at=e.created_at, title=e.summary, direction=e.direction, source="Invoice / E-bill",
                               by=None, milestone=e.milestone, document_key=None))  # fmt: skip
    for it in b.interactions.get(d.id, []):
        out.append(ActivityOut(at=it.created_at, title=f"{it.channel.capitalize()}: {it.summary}", direction=it.direction,
                               source="Interactions", by=None, milestone=False, document_key=None))  # fmt: skip
    out.sort(key=lambda a: a.at, reverse=True)
    return out


# ---- one deal ---------------------------------------------------------------------------------------------


async def _deal(session: AsyncSession, deal_id: uuid.UUID, lock: bool = False) -> Deal:
    await ensure_deals(session)
    d = await session.get(Deal, deal_id, with_for_update=lock)
    if d is None:
        raise NotFound("Deal not found.")
    return d


def _invoice_card(
    inv: Invoice | None, receipts: list[InvoiceReceipt], qty: Decimal | None, rate: int | None
) -> InvoiceCard | None:
    if inv is None:
        return None
    got = sum(r.amount_paise for r in receipts)
    total = inv.grand_total_paise or 0
    return InvoiceCard(id=inv.id, number=inv.invoice_number, status=inv.billing_status or "issued",
                       invoice_date=inv.invoice_date, due_date=inv.due_date, quantity=qty, rate_paise=rate,
                       taxable_paise=(inv.total_taxable_paise or 0) - (inv.other_charges_paise or 0),
                       cgst_paise=inv.total_cgst_paise or 0, sgst_paise=inv.total_sgst_paise or 0,
                       igst_paise=inv.total_igst_paise or 0, other_charges_paise=inv.other_charges_paise or 0,
                       total_paise=total, received_paise=got, outstanding_paise=total - got if inv.billing_status
                       not in ("draft", "verified") else 0, payment_terms_days=inv.payment_terms_days,
                       verified_at=inv.verified_at, issued_at=inv.issued_at, sent_at=inv.sent_at)  # fmt: skip


def _invoice_block(d: Deal, b: _Bundle) -> str | None:
    """Why a sales invoice can't be raised now (None = it can)."""
    if d.kind != "sale":
        return None
    o = b.orders.get(d.order_id) if d.order_id else None
    if o is None:
        return "No order yet: a provisional deal is invoiced once its order exists."
    if d.cancelled_reason or o["status"] == "cancelled":
        return "The deal is cancelled."
    if d.on_hold:
        return "The deal is on hold."
    if _issued(b.invoices.get(d.id, [])):
        return None  # already invoiced: the card shows it
    if o["status"] != "shipped":
        qty = f"{o['quantity']:,.0f} {o['unit']}"
        return (f"No dispatch recorded yet: the order is {ORDER_LABEL.get(o['status'], o['status']).lower()}. "
                f"It is billed when all {qty} are dispatched (order marked Shipped).")  # fmt: skip
    return None


async def detail(session: AsyncSession, deal_id: uuid.UUID) -> DealDetail:
    d = await _deal(session, deal_id)
    b = await _bundle(session, [d])
    await _refresh(session, [d], b)
    names = await _names(session, {e.actor_id for e in b.events.get(d.id, [])}
                         | {i.actor_id for i in b.interactions.get(d.id, [])}
                         | {r.actor_id for v in b.receipts.values() for r in v}
                         | {e["actor_id"] for p in b.pos.values() for e in p["events"]})  # fmt: skip
    acts = await _activity(session, d, b, names)
    o = b.orders.get(d.order_id) if d.order_id else None
    p = b.pos.get(d.po_id) if d.po_id else None
    invs = b.invoices.get(d.id, [])
    pick = _issued(invs) or invs
    inv: Invoice | None = pick[-1] if pick else None
    qty = rate = None
    if inv is not None:
        ln = await ledger.line_of(session, inv)
        if ln is not None:
            qty, rate = ln.quantity, ln.unit_price_paise
    payable = None
    if b.sinv.get(d.id):
        from app.billing import payables

        payable = await payables.one(session, b.sinv[d.id][-1].id)
    return DealDetail(
        row=_row(d, b, acts[0] if acts else None), customer_id=d.customer_id, supplier_id=d.supplier_id,
        order_id=d.order_id, po_id=d.po_id, item=d.item, quantity=d.quantity, unit=d.unit,
        dispatched_qty=(o["quantity"] if o["status"] == "shipped" else Decimal(0)) if o else None,
        received_qty=Decimal(p["received_qty"]) if p else None, payment_terms_days=_terms(d, None),
        billing_basis=d.billing_basis, contact=d.contact, note=d.note, on_hold=d.on_hold, hold_reason=d.hold_reason,
        cancelled_reason=d.cancelled_reason or (o["cancel_reason"] if o and o["status"] == "cancelled" else None),
        created_at=d.created_at, ship_date=o["ship_date"] if o else (p["expected_date"] if p else None),
        invoice=_invoice_card(inv, b.receipts.get(inv.id, []) if inv else [], qty, rate),
        invoice_block=_invoice_block(d, b), payable=payable, documents=_documents(d, b),
        interactions=await interactions_for(session, deal_id=d.id), activity=acts,
    )  # fmt: skip


def _terms(d: Deal, customer: dict[str, Any] | None) -> int | None:
    return d.payment_terms_days or (customer or {}).get("payment_terms_days")


# ---- create / edit / archive / interactions --------------------------------------------------------------


async def _event(session: AsyncSession, d: Deal, actor: uuid.UUID | None, kind: str, summary: str,
                 direction: str = "internal", milestone: bool = False, data: dict[str, Any] | None = None) -> None:  # fmt: skip
    session.add(DealEvent(deal_id=d.id, kind=kind, summary=summary, direction=direction, milestone=milestone,
                          data=data or {}, actor_id=actor, created_at=datetime.now(UTC)))  # fmt: skip
    await audit.record(session, actor_id=actor, action="update", entity_type="deal", entity_id=d.id,
                       summary=f"{d.number}: {summary}")  # fmt: skip
    await session.flush()


async def create(session: AsyncSession, actor: uuid.UUID, body: DealCreateIn) -> DealDetail:
    """A deal from an enquiry (sale) or a purchase requirement: provisional until its order / PO exists."""
    if body.kind == "sale":
        cid = await customers.find_by_name(session, body.company)
        if cid is None:
            raise NotFound(f"No customer called {body.company}. Add the customer in Orders first.")
        same = select(Deal).where(Deal.customer_id == cid)
    else:
        sid = await purchasing.find_supplier(session, body.company)
        if sid is None:
            raise NotFound(f"No supplier called {body.company}.")
        same = select(Deal).where(Deal.supplier_id == sid)
    ref = (body.reference or "").strip() or None
    existing = list((await session.execute(same)).scalars())
    if ref:
        hit = next((d for d in existing if (d.reference or "").lower() == ref.lower()), None)
        if hit is not None:  # same company + same reference: never two deals
            raise Conflict(
                f"{hit.number} already has {ref} for this company.", details={"deal_id": str(hit.id)}
            )
    if not body.force:
        soon = datetime.now(UTC) - timedelta(days=30)
        near = next((d for d in existing if (d.item or "").lower() == body.item.strip().lower()
                     and d.quantity == body.quantity and d.created_at >= soon), None)  # fmt: skip
        if near is not None:
            raise Conflict(f"{near.number} looks the same (same company, item and quantity in the last 30 days). "
                           "Create anyway?", details={"deal_id": str(near.id), "warning": True})  # fmt: skip
    d = Deal(number=await _next_number(session), kind=body.kind, name=f"{body.item.strip()}" + (f" – {ref}" if ref else ""),
             customer_id=cid if body.kind == "sale" else None, supplier_id=sid if body.kind == "purchase" else None,
             reference=ref, reference_kind="enquiry", provisional=True, item=body.item.strip(), quantity=body.quantity,
             unit=body.unit, expected_value_paise=body.expected_value_paise, payment_terms_days=body.payment_terms_days,
             contact=body.contact, note=body.note, created_by=actor, status="Enquiry Received")  # fmt: skip
    session.add(d)
    await session.flush()
    await _event(session, d, actor, "created", "Deal created" + (f" from enquiry {ref}" if ref else ""),
                 "incoming", milestone=True)  # fmt: skip
    return await detail(session, d.id)


async def edit(session: AsyncSession, actor: uuid.UUID, deal_id: uuid.UUID, body: DealEditIn) -> DealDetail:
    d = await _deal(session, deal_id, lock=True)
    b = await _bundle(session, [d])
    changes = []
    for f in ("name", "contact", "note", "payment_terms_days"):
        v = getattr(body, f)
        if v is not None and v != getattr(d, f):
            setattr(d, f, v)
            changes.append(f.replace("_", " "))
    if body.expected_value_paise is not None and body.expected_value_paise != d.expected_value_paise:
        if _issued(b.invoices.get(d.id, [])):
            raise DomainError("The value can't change once an invoice is issued.")
        d.expected_value_paise = body.expected_value_paise
        changes.append("value")
    if changes:
        await _event(session, d, actor, "edited", "Deal details changed: " + ", ".join(changes))
    return await detail(session, d.id)


async def archive(session: AsyncSession, actor: uuid.UUID, deal_id: uuid.UUID) -> DealDetail:
    """Hidden from the default list. Not while money is still owed on it."""
    d = await _deal(session, deal_id, lock=True)
    det = await detail(session, d.id)
    if (det.invoice and det.invoice.outstanding_paise > 0) or (det.payable and det.payable.outstanding_paise > 0
                                                              and det.payable.status != "rejected"):  # fmt: skip
        raise DomainError("Money is still outstanding on this deal; it can't be archived.")
    d.archived_at = datetime.now(UTC)
    await _event(session, d, actor, "archived", "Deal archived")
    return await detail(session, d.id)


async def add_interaction(
    session: AsyncSession, actor: uuid.UUID, deal_id: uuid.UUID, body: InteractionIn
) -> InteractionOut:
    d = await _deal(session, deal_id)
    if body.next_follow_up is not None and body.next_follow_up < clock.today():
        raise DomainError("The next follow-up can't be in the past.")
    invs = await ledger.deal_invoices(session, [d.id])
    it = Interaction(deal_id=d.id, customer_id=d.customer_id, supplier_id=d.supplier_id,
                     invoice_id=next((i.id for i in reversed(invs) if i.billing_status in ("issued", "sent")), None),
                     channel=body.channel, direction=body.direction, contact=body.contact, summary=body.summary,
                     next_follow_up=body.next_follow_up, actor_id=actor)  # fmt: skip
    session.add(it)
    await session.flush()
    await audit.record(session, actor_id=actor, action="create", entity_type="interaction", entity_id=it.id,
                       summary=f"{d.number}: {body.channel} logged")  # fmt: skip
    return (await interactions_for(session, deal_id=d.id))[0]


# ---- sales invoice: draft -> verified -> issued -> sent ---------------------------------------------------


async def _profile(session: AsyncSession, tenant_id: uuid.UUID | None) -> dict[str, Any]:
    """The company's GST state, GSTIN and invoice prefix (setting `billing-profile`; sensible defaults)."""
    try:
        p = await kv.get_setting(session, "billing-profile")
    except (NotFound, ValueError):
        p = {}
    name = "Company"
    if tenant_id is not None:
        t = await session.get(Tenant, tenant_id)
        name = t.name if t else name
    # continue the company's own series: the prefix of its latest issued invoice (DMC/2026-27/0042), else initials
    initials = "".join(w[0] for w in name.replace(".", "").split() if w[:1].isalpha()).upper()[:4]
    prefix = p.get("prefix") or await ledger.series_prefix(session) or initials
    return {
        "name": name,
        "state_code": p.get("state_code", "27"),
        "gstin": p.get("gstin"),
        "prefix": prefix or "INV",
    }


async def _draft_of(session: AsyncSession, d: Deal) -> Invoice | None:
    return next(
        (i for i in await ledger.deal_invoices(session, [d.id]) if i.billing_status in ("draft", "verified")),
        None,
    )


async def generate_invoice(session: AsyncSession, actor: uuid.UUID, deal_id: uuid.UUID) -> DealDetail:
    """A draft from the shipped order: quantity dispatched, rate = order rate, GST by state, customer terms."""
    d = await _deal(session, deal_id, lock=True)
    b = await _bundle(session, [d])
    block = _invoice_block(d, b)
    if block:
        raise DomainError(block)
    if b.invoices.get(d.id):
        raise DomainError("This deal already has an invoice (one per dispatch).")
    o = b.orders[d.order_id]  # type: ignore[index]
    cust = (await customers.briefs(session, [o["customer_id"]]))[o["customer_id"]]
    prof = await _profile(session, d.tenant_id)
    inv = await ledger.create_draft(
        session, deal_id=d.id, customer_id=o["customer_id"], order_id=o["id"], product_id=None, product_name=o["product"],
        qty=o["quantity"], unit=o["unit"], rate=o["unit_price_paise"], terms_days=_terms(d, cust) or 30,
        seller={"name": prof["name"], "gstin": prof["gstin"], "state_code": prof["state_code"]},
        buyer={"name": cust["name"], "gstin": cust["gstin"], "state_code": cust["state_code"]},
    )  # fmt: skip
    await _event(session, d, actor, "invoice_draft", "Sales invoice draft generated", "internal",
                 data={"document_key": f"invoice:{inv.id}"})  # fmt: skip
    await events.emit(session, "invoice.draft_created", {"deal": d.number, "invoice_id": str(inv.id)})
    return await detail(session, d.id)


async def edit_draft(
    session: AsyncSession, actor: uuid.UUID, deal_id: uuid.UUID, body: DraftEditIn
) -> DealDetail:
    """Quantity (up to what was dispatched), rate, other charges, terms. Any edit clears the verification."""
    d = await _deal(session, deal_id, lock=True)
    inv = await _draft_of(session, d)
    if inv is None:
        raise DomainError(
            "There is no draft to change (an issued invoice is never edited; use a credit note)."
        )
    o = (await orders.facts(session, [d.order_id]))[d.order_id]  # type: ignore[index,list-item]
    ln = await ledger.line_of(session, inv)
    qty = body.quantity if body.quantity is not None else ln.quantity or Decimal(0)
    if qty > o["quantity"]:
        raise DomainError(f"Only {o['quantity']:,.0f} {o['unit']} were dispatched.")
    rate = body.rate_paise if body.rate_paise is not None else ln.unit_price_paise or 0
    other = body.other_charges_paise if body.other_charges_paise is not None else inv.other_charges_paise or 0
    terms = body.payment_terms_days if body.payment_terms_days is not None else inv.payment_terms_days or 30
    await ledger.set_amounts(session, inv, qty, rate, other, terms)
    was = inv.billing_status
    inv.billing_status, inv.verified_by, inv.verified_at = "draft", None, None
    await _event(
        session,
        d,
        actor,
        "invoice_edit",
        "Invoice draft changed" + (" · verification cleared" if was == "verified" else ""),
    )
    return await detail(session, d.id)


async def verify_invoice(session: AsyncSession, actor: uuid.UUID, deal_id: uuid.UUID) -> DealDetail:
    d = await _deal(session, deal_id, lock=True)
    inv = await _draft_of(session, d)
    if inv is None or inv.billing_status != "draft":
        raise DomainError("Only a draft invoice can be verified.")
    inv.billing_status, inv.verified_by, inv.verified_at = "verified", actor, datetime.now(UTC)
    await _event(
        session, d, actor, "invoice_verified", "Invoice draft verified against the order and dispatch"
    )
    return await detail(session, d.id)


async def issue_invoice(session: AsyncSession, actor: uuid.UUID, deal_id: uuid.UUID) -> DealDetail:
    """In one transaction: the next number, locked for good, a receivable (due = issue date + terms), the deal
    moves to Invoiced, and `invoice.issued` (once)."""
    d = await _deal(session, deal_id, lock=True)
    inv = await _draft_of(session, d)
    if inv is None:
        if any(i.billing_status in ("issued", "sent") for i in await ledger.deal_invoices(session, [d.id])):
            return await detail(session, d.id)  # already issued: the same request twice has one effect
        raise DomainError("There is no invoice to issue.")
    if inv.billing_status != "verified":
        raise DomainError("Accounts must verify the draft before it is issued.")
    inv = await ledger.get_invoice(session, inv.id, lock=True)
    assert inv is not None
    today = clock.today()
    prof = await _profile(session, d.tenant_id)
    fy = financial_year(today)
    inv.invoice_number = await ledger.next_number(session, prof["prefix"], fy)
    inv.invoice_date, inv.financial_year = today, fy
    inv.due_date = today + timedelta(days=inv.payment_terms_days or 30)
    inv.billing_status, inv.issued_by, inv.issued_at = "issued", actor, datetime.now(UTC)
    await _event(session, d, actor, "invoice_issued", f"Invoice {inv.invoice_number} issued · {inr(inv.grand_total_paise or 0)}",
                 "outgoing", milestone=True, data={"document_key": f"invoice:{inv.id}"})  # fmt: skip
    await events.emit(
        session, "invoice.issued", {"invoice_id": str(inv.id), "number": inv.invoice_number, "deal": d.number}
    )
    return await detail(session, d.id)


async def send_invoice(
    session: AsyncSession, actor: uuid.UUID, deal_id: uuid.UUID, body: SendIn
) -> DealDetail:
    d = await _deal(session, deal_id, lock=True)
    inv = next(
        (i for i in await ledger.deal_invoices(session, [d.id]) if i.billing_status in ("issued", "sent")),
        None,
    )
    if inv is None:
        raise DomainError("Only an issued invoice can be sent.")
    if inv.billing_status == "issued":
        inv.billing_status, inv.sent_at = "sent", datetime.now(UTC)
    session.add(Interaction(deal_id=d.id, customer_id=d.customer_id, invoice_id=inv.id, channel=body.channel,
                            direction="outgoing", contact=body.contact,
                            summary=f"Invoice {inv.invoice_number} sent", actor_id=actor))  # fmt: skip
    await _event(
        session, d, actor, "invoice_sent", f"Invoice {inv.invoice_number} sent by {body.channel}", "outgoing"
    )
    await events.emit(session, "invoice.sent", {"invoice_id": str(inv.id)})
    return await detail(session, d.id)


async def deal_refs(session: AsyncSession, *, order_ids: list[uuid.UUID] | None = None,
                    po_ids: list[uuid.UUID] | None = None) -> dict[uuid.UUID, tuple[uuid.UUID, str]]:  # fmt: skip
    """Order / PO -> (deal id, TXN number), for the chips other modules show."""
    await ensure_deals(session)
    q = select(Deal)
    if order_ids is not None:
        q = q.where(Deal.order_id.in_(order_ids))
    if po_ids is not None:
        q = q.where(Deal.po_id.in_(po_ids))
    out: dict[uuid.UUID, tuple[uuid.UUID, str]] = {}
    for d in (await session.execute(q)).scalars():
        k = d.order_id or d.po_id
        if k is not None:
            out[k] = (d.id, d.number)
    return out


_ = func
