"""Accounts receivables: what customers owe, as of any month.

Per issued invoice: outstanding = grand total - receipts (cash, advances adjusted, credit notes, opening), dated
on or before the as-of date. Three dates are kept apart: the original due date (contract), the promised date
(latest promise, a new row each time) and the actual payment dates (receipts). A promise never stops an invoice
being overdue; it only sets when the money is expected.
"""

import csv
import io
import uuid
from collections import defaultdict
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Deal, Interaction, PaymentPromise
from app.billing.schemas import (
    ArCards,
    ArCustomer,
    ArFollowUpIn,
    ArInvoice,
    ArOut,
    ArRow,
    ArStatus,
    InteractionOut,
    Period,
    PromiseIn,
    PromiseOut,
    ReceiptIn,
    ReceiptOut,
)
from app.core import audit, clock
from app.core.errors import DomainError, NotFound
from app.core.models import User
from app.customers import service as customers
from app.invoices import ledger
from app.invoices.models import Invoice

IST = ZoneInfo("Asia/Kolkata")  # business dates
STATUS_RANK: dict[str, int] = {"overdue": 0, "due_week": 1, "promise": 2, "not_due": 3}


def period(month: str | None) -> Period:
    """The selected month (YYYY-MM); as of its last day, or today for the current month."""
    today = clock.today()
    if month:
        try:
            y, m = (int(x) for x in month.split("-"))
            start = date(y, m, 1)
        except ValueError as e:
            raise DomainError("Month must look like 2026-11.") from e
    else:
        start = today.replace(day=1)
    if start > today:
        raise DomainError("That month hasn't started yet.")
    nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
    as_of = min(nxt - timedelta(days=1), today)
    return Period(month=f"{start:%Y-%m}", start=start, as_of=as_of, live=as_of == today)


def _end(as_of: date) -> datetime | None:
    """Records made up to the end of a past day (Asia/Kolkata); None for the current period (everything so far)."""
    if as_of >= clock.today():
        return None
    return datetime.combine(as_of + timedelta(days=1), datetime.min.time(), tzinfo=IST)


async def _names(session: AsyncSession, ids: set[uuid.UUID | None]) -> dict[uuid.UUID, str]:
    ids_ = [i for i in ids if i]
    if not ids_:
        return {}
    return {
        i: n
        for i, n in (await session.execute(select(User.id, User.full_name).where(User.id.in_(ids_)))).all()
    }


class _Inv:
    """One open invoice as of a date."""

    def __init__(self, inv: Invoice, received: int, promises: list[PaymentPromise], as_of: date):
        self.inv = inv
        self.total = inv.grand_total_paise or 0
        self.received = received
        self.outstanding = self.total - received
        self.due = inv.due_date or (
            (inv.invoice_date or as_of) + timedelta(days=inv.payment_terms_days or 30)
        )
        self.promises = promises
        self.promised = promises[-1].promised_on if promises else None
        self.expected = self.promised or self.due
        self.days_overdue = max(0, (as_of - self.due).days)
        week_end = as_of + timedelta(days=6)
        self.status: ArStatus = (
            "overdue" if self.due < as_of
            else "due_week" if self.expected <= week_end
            else "promise" if self.promised
            else "not_due"
        )  # fmt: skip
        self.expected_week = as_of <= self.expected <= week_end
        self.part_paid = 0 < received < self.total


async def _open(session: AsyncSession, as_of: date, customer_id: uuid.UUID | None = None) -> list[_Inv]:
    invs = await ledger.issued_invoices(session, as_of, customer_id)
    recs = await ledger.receipts(session, [i.id for i in invs], as_of)
    got: dict[uuid.UUID, int] = defaultdict(int)
    for r in recs:
        got[r.invoice_id] += r.amount_paise
    proms: dict[uuid.UUID, list[PaymentPromise]] = defaultdict(list)
    ids = [i.id for i in invs if (i.grand_total_paise or 0) - got[i.id] > 0]
    if ids:
        q = (
            select(PaymentPromise)
            .where(PaymentPromise.invoice_id.in_(ids))
            .order_by(PaymentPromise.created_at)
        )
        if (end := _end(as_of)) is not None:
            q = q.where(PaymentPromise.created_at <= end)
        for p in (await session.execute(q)).scalars():
            proms[p.invoice_id].append(p)
    return [
        _Inv(i, got[i.id], proms[i.id], as_of) for i in invs if (i.grand_total_paise or 0) - got[i.id] > 0
    ]


async def receivables(session: AsyncSession, month: str | None, q: str | None = None,
                      status: str | None = None) -> ArOut:  # fmt: skip
    p = period(month)
    open_ = await _open(session, p.as_of)
    by_c: dict[uuid.UUID, list[_Inv]] = defaultdict(list)
    for x in open_:
        by_c[x.inv.customer_id].append(x)
    info = await customers.briefs(session, list(by_c))
    latest = await _latest_updates(session, by_c, p.as_of)
    rows: list[ArRow] = []
    for cid, xs in by_c.items():
        c = info.get(cid, {"name": "Unknown customer", "gstin": None, "phone": None})
        st = min((x.status for x in xs), key=lambda s: STATUS_RANK[s])
        first = min(xs, key=lambda x: x.due)
        upd = latest.get(cid)
        rows.append(ArRow(customer_id=cid, name=c["name"], gstin=c["gstin"], phone=c["phone"],
                          outstanding_paise=sum(x.outstanding for x in xs), open_invoices=len(xs),
                          earliest_due=first.due, days_overdue=first.days_overdue, status=st,
                          part_paid=any(x.part_paid for x in xs), has_promise=any(x.promised for x in xs), latest_update=upd[1] if upd else None,
                          latest_at=upd[0] if upd else None))  # fmt: skip
    rows.sort(key=lambda r: -r.outstanding_paise)
    counts = {"all": len(rows), "overdue": sum(r.status == "overdue" for r in rows), "due_week": sum(r.status == "due_week" for r in rows), "promise": sum(r.has_promise for r in rows),
              "part_paid": sum(r.part_paid for r in rows)}  # fmt: skip
    overdue = [x for x in open_ if x.status == "overdue"]
    cash, n_cash = await ledger.cash_received(session, p.start, p.as_of)
    cards = ArCards(
        total_paise=sum(x.outstanding for x in open_), total_customers=len(by_c), total_invoices=len(open_),
        overdue_paise=sum(x.outstanding for x in overdue),
        overdue_customers=len({x.inv.customer_id for x in overdue}),
        oldest_overdue_days=max((x.days_overdue for x in overdue), default=None),
        expected_week_paise=sum(x.outstanding for x in open_ if x.expected_week),
        week_from=p.as_of, week_to=p.as_of + timedelta(days=6), received_paise=cash, receipts=n_cash,
    )  # fmt: skip
    if status and status != "all":
        rows = [
            r
            for r in rows
            if (
                r.part_paid
                if status == "part_paid"
                else r.has_promise
                if status == "promise"
                else r.status == status
            )
        ]
    if q and q.strip():
        needle = q.strip().lower()
        nums = {x.inv.customer_id for x in open_ if needle in (x.inv.invoice_number or "").lower()}
        rows = [r for r in rows if needle in r.name.lower() or needle in (r.gstin or "").lower()
                or needle in (r.phone or "") or r.customer_id in nums]  # fmt: skip
    return ArOut(period=p, cards=cards, rows=rows, counts=counts)


async def _latest_updates(session: AsyncSession, by_c: dict[uuid.UUID, list[_Inv]],
                          as_of: date) -> dict[uuid.UUID, tuple[date, str]]:  # fmt: skip
    """Newest of: a follow-up, a payment in the last 45 days, a promise made."""
    best: dict[uuid.UUID, tuple[datetime, str]] = {}

    def offer(cid: uuid.UUID, at: datetime, text: str) -> None:
        if cid not in best or at >= best[cid][0]:
            best[cid] = (at, text)

    for cid, xs in by_c.items():
        for x in xs:
            for p in x.promises:
                offer(cid, p.created_at, f"Promised {inr(p.amount_paise)} by {p.promised_on:%-d %b}")
    recs = await ledger.receipts(session, [x.inv.id for xs in by_c.values() for x in xs], as_of)
    inv_c = {x.inv.id: cid for cid, xs in by_c.items() for x in xs}
    for r in recs:
        if (as_of - r.received_on).days <= 45 and r.kind != "opening":
            offer(inv_c[r.invoice_id], datetime.combine(r.received_on, datetime.min.time(), tzinfo=IST),
                  f"Received {inr(r.amount_paise)}")  # fmt: skip
    if by_c:
        q = (
            select(Interaction)
            .where(Interaction.customer_id.in_(list(by_c)))
            .order_by(Interaction.created_at)
        )
        if (end := _end(as_of)) is not None:
            q = q.where(Interaction.created_at <= end)
        for i in (await session.execute(q)).scalars():
            assert i.customer_id is not None
            offer(i.customer_id, i.created_at, f"{i.channel.capitalize()}: {i.summary}")
    return {cid: (at.astimezone(IST).date(), text) for cid, (at, text) in best.items()}


def inr(paise: int) -> str:
    """₹2,80,254 (Indian grouping, whole rupees)."""
    n = round(abs(paise) / 100)
    head, tail = str(n)[:-3], str(n)[-3:]
    groups: list[str] = []
    while len(head) > 2:
        head, groups = head[:-2], [head[-2:], *groups]
    return f"{'-' if paise < 0 else ''}₹" + ",".join([g for g in [head, *groups] if g] + [tail])


async def interactions_for(session: AsyncSession, *, customer_id: uuid.UUID | None = None,
                           supplier_id: uuid.UUID | None = None, deal_id: uuid.UUID | None = None,
                           as_of: date | None = None) -> list[InteractionOut]:  # fmt: skip
    q = select(Interaction)
    if customer_id is not None:
        q = q.where(Interaction.customer_id == customer_id)
    if supplier_id is not None:
        q = q.where(Interaction.supplier_id == supplier_id)
    if deal_id is not None:
        q = q.where(Interaction.deal_id == deal_id)
    if as_of is not None and (end := _end(as_of)) is not None:
        q = q.where(Interaction.created_at <= end)
    items = list((await session.execute(q.order_by(Interaction.created_at.desc()).limit(100))).scalars())
    names = await _names(session, {i.actor_id for i in items})
    inv_ids = [i.invoice_id for i in items if i.invoice_id]
    nums = (
        {i.id: i.invoice_number for i in await ledger.issued_invoices(session, clock.today(), ids=inv_ids)}
        if inv_ids
        else {}
    )
    deal_ids = [i.deal_id for i in items if i.deal_id]
    deals = (
        {d.id: d.number for d in (await session.execute(select(Deal).where(Deal.id.in_(deal_ids)))).scalars()}
        if deal_ids
        else {}
    )
    return [InteractionOut(id=i.id, channel=i.channel, direction=i.direction, contact=i.contact, summary=i.summary,
                           next_follow_up=i.next_follow_up, invoice_number=nums.get(i.invoice_id) if i.invoice_id else None,
                           deal_number=deals.get(i.deal_id) if i.deal_id else None, at=i.created_at,
                           by=names.get(i.actor_id) if i.actor_id else None) for i in items]  # fmt: skip


async def customer(session: AsyncSession, customer_id: uuid.UUID, month: str | None) -> ArCustomer:
    p = period(month)
    info = (await customers.briefs(session, [customer_id])).get(customer_id)
    if info is None:
        raise NotFound("Customer not found.")
    open_ = await _open(session, p.as_of, customer_id)
    recs = await ledger.receipts(session, [x.inv.id for x in open_], p.as_of)
    by_inv: dict[uuid.UUID, list[ReceiptOut]] = defaultdict(list)
    names = await _names(
        session, {r.actor_id for r in recs} | {pr.actor_id for x in open_ for pr in x.promises}
    )
    for r in recs:
        by_inv[r.invoice_id].append(ReceiptOut(id=r.id, kind=r.kind, amount_paise=r.amount_paise, received_on=r.received_on,
                                               method=r.method, reference=r.reference, note=r.note,
                                               by=names.get(r.actor_id) if r.actor_id else None))  # fmt: skip
    deal_ids = [x.inv.deal_id for x in open_ if x.inv.deal_id]
    deal_num = (
        {d.id: d.number for d in (await session.execute(select(Deal).where(Deal.id.in_(deal_ids)))).scalars()}
        if deal_ids
        else {}
    )
    order_ids = [x.inv.order_id for x in open_ if x.inv.order_id and not x.inv.deal_id]
    by_order = (
        {
            d.order_id: d
            for d in (await session.execute(select(Deal).where(Deal.order_id.in_(order_ids)))).scalars()
        }
        if order_ids
        else {}
    )
    invoices = []
    for x in sorted(open_, key=lambda x: (STATUS_RANK[x.status], x.due)):
        d_id = x.inv.deal_id or (by_order[x.inv.order_id].id if x.inv.order_id in by_order else None)
        d_no = (
            deal_num.get(x.inv.deal_id)
            if x.inv.deal_id
            else (by_order[x.inv.order_id].number if x.inv.order_id in by_order else None)
        )
        invoices.append(ArInvoice(
            id=x.inv.id, number=x.inv.invoice_number, invoice_date=x.inv.invoice_date, due_date=x.due,
            total_paise=x.total, received_paise=x.received, outstanding_paise=x.outstanding,
            days_overdue=x.days_overdue, promised_on=x.promised, expected_on=x.expected, status=x.status,
            part_paid=x.part_paid, deal_id=d_id, deal_number=d_no,
            promises=[PromiseOut(amount_paise=pr.amount_paise, promised_on=pr.promised_on, note=pr.note, at=pr.created_at,
                                 by=names.get(pr.actor_id) if pr.actor_id else None) for pr in reversed(x.promises)],
            receipts=by_inv.get(x.inv.id, []),
        ))  # fmt: skip
    return ArCustomer(customer_id=customer_id, name=info["name"], gstin=info["gstin"], phone=info["phone"],
                      email=info["email"], city=info["city"], payment_terms_days=info["payment_terms_days"], period=p,
                      invoices=invoices,
                      interactions=await interactions_for(session, customer_id=customer_id, as_of=p.as_of))  # fmt: skip


# ---- actions (always today) --------------------------------------------------------------------------


async def _deal_of(session: AsyncSession, inv: Invoice) -> uuid.UUID | None:
    if inv.deal_id:
        return inv.deal_id
    if inv.order_id:
        return (
            await session.execute(select(Deal.id).where(Deal.order_id == inv.order_id))
        ).scalar_one_or_none()
    return None


async def log_follow_up(
    session: AsyncSession, actor: uuid.UUID, customer_id: uuid.UUID, body: ArFollowUpIn
) -> InteractionOut:
    if customer_id not in await customers.briefs(session, [customer_id]):
        raise NotFound("Customer not found.")
    deal_id = None
    if body.invoice_id is not None:
        inv = await ledger.get_invoice(session, body.invoice_id)
        if inv is None or inv.customer_id != customer_id:
            raise NotFound("That invoice isn't this customer's.")
        deal_id = await _deal_of(session, inv)
    if body.next_follow_up is not None and body.next_follow_up < clock.today():
        raise DomainError("The next follow-up can't be in the past.")
    i = Interaction(customer_id=customer_id, invoice_id=body.invoice_id, deal_id=deal_id, channel=body.channel,
                    direction=body.direction, contact=body.contact, summary=body.note,
                    next_follow_up=body.next_follow_up, actor_id=actor)  # fmt: skip
    session.add(i)
    await session.flush()
    await audit.record(session, actor_id=actor, action="create", entity_type="interaction", entity_id=i.id,
                       summary=f"Follow-up ({body.channel}) logged")  # fmt: skip
    return (await interactions_for(session, customer_id=customer_id))[0]


async def _open_invoice(session: AsyncSession, invoice_id: uuid.UUID) -> tuple[Invoice, int]:
    inv = await ledger.get_invoice(session, invoice_id, lock=True)
    if inv is None or inv.billing_status in ("draft", "verified"):
        raise NotFound("Issued invoice not found.")
    got = sum(r.amount_paise for r in await ledger.receipts(session, [inv.id], clock.today()))
    return inv, (inv.grand_total_paise or 0) - got


async def add_promise(
    session: AsyncSession, actor: uuid.UUID, invoice_id: uuid.UUID, body: PromiseIn
) -> ArCustomer:
    """Update commitment: a new promise row (older ones are kept)."""
    inv, outstanding = await _open_invoice(session, invoice_id)
    if outstanding <= 0:
        raise DomainError("This invoice is fully paid.")
    if body.amount_paise > outstanding:
        raise DomainError(f"The promise is more than the {inr(outstanding)} outstanding.")
    if body.promised_on < clock.today():
        raise DomainError("A promised date can't be in the past.")
    pr = PaymentPromise(invoice_id=inv.id, amount_paise=body.amount_paise, promised_on=body.promised_on,
                        note=body.note, actor_id=actor)  # fmt: skip
    session.add(pr)
    await session.flush()
    await audit.record(session, actor_id=actor, action="create", entity_type="payment_promise", entity_id=pr.id,
                       summary=f"{inv.invoice_number}: promise {inr(body.amount_paise)} by {body.promised_on}")  # fmt: skip
    return await customer(session, inv.customer_id, None)


async def add_receipt(
    session: AsyncSession, actor: uuid.UUID, invoice_id: uuid.UUID, body: ReceiptIn
) -> ArCustomer:
    """Money received (or an advance adjusted / a credit note): outstanding is recomputed everywhere."""
    inv, outstanding = await _open_invoice(session, invoice_id)
    if body.received_on > clock.today():
        raise DomainError("A receipt can't be dated in the future.")
    if inv.invoice_date and body.received_on < inv.invoice_date:
        raise DomainError("A receipt can't be dated before the invoice.")
    if body.amount_paise > outstanding:
        raise DomainError(f"Only {inr(outstanding)} is outstanding on {inv.invoice_number}.")
    if body.reference:  # the same UTR / cheque twice is the same money
        dup = [
            r
            for r in await ledger.receipts(session, [inv.id], clock.today())
            if r.reference == body.reference.strip()
        ]
        if dup:
            raise DomainError(
                f"A receipt with reference {body.reference} is already recorded on this invoice."
            )
    r = await ledger.add_receipt(session, actor, inv, body.kind, body.amount_paise, body.received_on, body.method,
                                 body.reference.strip() if body.reference else None, body.note)  # fmt: skip
    await audit.record(session, actor_id=actor, action="create", entity_type="invoice_receipt", entity_id=r.id,
                       summary=f"{inv.invoice_number}: {body.kind} {inr(body.amount_paise)}")  # fmt: skip
    deal_id = await _deal_of(session, inv)
    if deal_id is not None:
        from app.billing import deals

        await deals.refresh_status(session, deal_id)
    return await customer(session, inv.customer_id, None)


async def export_csv(session: AsyncSession, actor: uuid.UUID, month: str | None, q: str | None,
                     status: str | None) -> str:  # fmt: skip
    out = await receivables(session, month, q, status)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["Customer", "GSTIN", "Outstanding (Rs)", "Open invoices", "Earliest due", "Days overdue", "Status",
                "Part-paid", "Latest update"])  # fmt: skip
    for r in out.rows:
        w.writerow([r.name, r.gstin or "", f"{r.outstanding_paise / 100:.2f}", r.open_invoices, r.earliest_due or "",
                    r.days_overdue, r.status, "yes" if r.part_paid else "", r.latest_update or ""])  # fmt: skip
    await audit.record(session, actor_id=actor, action="export", entity_type="receivables", entity_id=None,
                       summary=f"Receivables exported · {out.period.month} · {len(out.rows)} rows")  # fmt: skip
    return buf.getvalue()
