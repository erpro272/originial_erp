"""Accounts payables: supplier invoices against our POs, and the approval workflow.

Outstanding = invoice total - bank-confirmed payments (a scheduled payment is only a plan; an executed one
counts once the bank statement confirms it). Rejected invoices are disputed: shown, but out of the total.

Workflow: 1 invoice received -> 2 accounts verification (three-way match PO <-> gate entry/QC <-> invoice must be
clean) -> 3 owner approval -> 4 scheduling -> 5 execution (UTR) -> 6 bank confirmation -> 7 settled.
Approval, scheduling, execution and confirmation are separate records. Only the owner approves, holds or
rejects; accounts can't skip approval. The approver doesn't execute the same payment unless the owner overrides
it with a reason (logged). Hold / reject cancel scheduled payments; releasing a hold goes back to approval.
"""

import csv
import io
import uuid
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.billing.models import Deal, PayableEvent, SupplierInvoice, SupplierPayment
from app.billing.receivables import _names, inr, interactions_for, period
from app.billing.schemas import (
    ApCards,
    ApEvent,
    ApInvoice,
    ApOut,
    ApPayment,
    ApRow,
    ApSupplier,
    BankConfirmIn,
    ExecuteIn,
    MatchLine,
    ScheduleIn,
    SupplierInvoiceIn,
)
from app.core import audit, clock, events
from app.core.errors import Conflict, DomainError, NotFound
from app.purchasing import service as purchasing

OPEN = ("pending_verif", "pending_owner", "approved", "scheduled")


def _q(x: Decimal, unit: str | None) -> str:
    return f"{x:,.3f}".rstrip("0").rstrip(".") + (f" {unit}" if unit else "")


def match(inv: SupplierInvoice, po: dict[str, Any] | None) -> list[MatchLine]:
    """Three-way match: what we ordered (PO), what QC accepted at the gate (GRN), what the supplier bills."""
    if po is None:
        return [MatchLine(check="po", ok=False, text="No purchase order linked")]
    out = [MatchLine(check="supplier", ok=po["supplier_id"] == inv.supplier_id,
                     text=f"Supplier is the one on {po['number']}" if po["supplier_id"] == inv.supplier_id
                     else f"Supplier differs from {po['number']} ({po['supplier']})")]  # fmt: skip
    acc, billed, unit = Decimal(po["received_qty"]), Decimal(inv.quantity), po["unit"]
    grn = (
        ", ".join(e["data"].get("ref") or "" for e in po["events"] if e["kind"] == "gate_entry")
        or "no gate entry yet"
    )
    if acc <= 0:
        out.append(
            MatchLine(
                check="quantity",
                ok=False,
                text=f"Nothing accepted at QC yet ({grn}): can't pay for goods not received",
            )
        )
    elif billed > acc:
        out.append(MatchLine(check="quantity", ok=False,
                             text=f"Bills {_q(billed, unit)} but QC accepted {_q(acc, unit)} ({grn})"))  # fmt: skip
    else:
        out.append(
            MatchLine(
                check="quantity",
                ok=True,
                text=f"Billed {_q(billed, unit)} of {_q(acc, unit)} accepted ({grn})",
            )
        )
    ok_rate = inv.rate_paise == po["rate_paise"]
    out.append(MatchLine(check="rate", ok=ok_rate,
                         text=f"Rate agrees with {po['number']} ({inr(po['rate_paise'])})" if ok_rate
                         else f"Rate {inr(inv.rate_paise)} vs {inr(po['rate_paise'])} on {po['number']}"))  # fmt: skip
    ok_amt = inv.taxable_paise <= po["value_paise"]
    out.append(MatchLine(check="amount", ok=ok_amt,
                         text=f"Taxable {inr(inv.taxable_paise)} within the PO value {inr(po['value_paise'])}"
                         if ok_amt else f"Taxable {inr(inv.taxable_paise)} is more than the PO value "
                         f"{inr(po['value_paise'])}"))  # fmt: skip
    return out


def _stage(inv: SupplierInvoice, pays: list[SupplierPayment]) -> int:
    live = [p for p in pays if p.status != "cancelled"]
    if inv.status == "paid":
        return 7
    if any(p.status == "executed" for p in live):
        return 6
    if inv.status == "scheduled":
        return 5
    return {"pending_verif": 2, "pending_owner": 3, "approved": 4}.get(inv.status, 3)


async def _load(session: AsyncSession, as_of: date, supplier_id: uuid.UUID | None = None,
                ids: list[uuid.UUID] | None = None) -> list[ApInvoice]:  # fmt: skip
    q = select(SupplierInvoice).where(SupplierInvoice.invoice_date <= as_of)
    if supplier_id is not None:
        q = q.where(SupplierInvoice.supplier_id == supplier_id)
    if ids is not None:
        q = q.where(SupplierInvoice.id.in_(ids))
    invs = list((await session.execute(q.order_by(SupplierInvoice.due_date))).scalars())
    if not invs:
        return []
    pays: dict[uuid.UUID, list[SupplierPayment]] = defaultdict(list)
    for p in (await session.execute(select(SupplierPayment).where(
            SupplierPayment.supplier_invoice_id.in_([i.id for i in invs])).order_by(SupplierPayment.created_at))).scalars():  # fmt: skip
        pays[p.supplier_invoice_id].append(p)
    evs: dict[uuid.UUID, list[PayableEvent]] = defaultdict(list)
    for e in (await session.execute(select(PayableEvent).where(
            PayableEvent.supplier_invoice_id.in_([i.id for i in invs])).order_by(PayableEvent.created_at))).scalars():  # fmt: skip
        evs[e.supplier_invoice_id].append(e)
    pos = await purchasing.po_facts(session, [i.po_id for i in invs if i.po_id])
    sup = await purchasing.supplier_names(session, list({i.supplier_id for i in invs}))
    deals = {d.id: d.number for d in (await session.execute(
        select(Deal).where(Deal.id.in_([i.deal_id for i in invs if i.deal_id])))).scalars()}  # fmt: skip
    names = await _names(session, {e.actor_id for v in evs.values() for e in v})
    out = []
    for i in invs:
        ps = pays[i.id]
        confirmed = sum(
            p.amount_paise
            for p in ps
            if p.status == "confirmed" and p.confirmed_on and p.confirmed_on <= as_of
        )
        planned = sum(p.amount_paise for p in ps if p.status in ("scheduled", "executed"))
        po = pos.get(i.po_id) if i.po_id else None
        m = match(i, po)
        grn = (
            ", ".join(e["data"].get("ref") or "" for e in po["events"] if e["kind"] == "gate_entry")
            if po
            else None
        )
        out.append(ApInvoice(
            id=i.id, number=i.number, supplier_id=i.supplier_id, supplier=sup.get(i.supplier_id, ""), po_id=i.po_id,
            po_number=po["number"] if po else None, grn=grn or None, deal_id=i.deal_id,
            deal_number=deals.get(i.deal_id) if i.deal_id else None, invoice_date=i.invoice_date, due_date=i.due_date,
            quantity=i.quantity, unit=po["unit"] if po else None, rate_paise=i.rate_paise,
            taxable_paise=i.taxable_paise, gst_paise=i.gst_paise, total_paise=i.total_paise, paid_paise=confirmed,
            scheduled_paise=planned, outstanding_paise=i.total_paise - confirmed,
            days_overdue=max(0, (as_of - i.due_date).days), status=i.status, stage=_stage(i, ps), match=m,
            match_ok=all(x.ok for x in m), hold_reason=i.hold_reason,
            payments=[ApPayment(id=p.id, amount_paise=p.amount_paise, scheduled_for=p.scheduled_for, status=p.status,
                                utr=p.utr, executed_on=p.executed_on, confirmed_on=p.confirmed_on,
                                override_reason=p.override_reason) for p in ps],
            events=[ApEvent(action=e.action, from_status=e.from_status, to_status=e.to_status, note=e.note,
                            at=e.created_at, by=names.get(e.actor_id) if e.actor_id else None) for e in evs[i.id]],
        ))  # fmt: skip
    return out


async def payables(
    session: AsyncSession, month: str | None, q: str | None = None, status: str | None = None
) -> ApOut:
    p = period(month)
    invs = [i for i in await _load(session, p.as_of) if i.outstanding_paise > 0 or i.status == "rejected"]
    week_end = p.as_of + timedelta(days=6)
    live = [i for i in invs if i.status != "rejected" and i.outstanding_paise > 0]
    by_s: dict[uuid.UUID, list[ApInvoice]] = defaultdict(list)
    for i in invs:
        by_s[i.supplier_id].append(i)
    rows = []
    for sid, xs in by_s.items():
        ok = [x for x in xs if x.status != "rejected"]
        first = min(ok, key=lambda x: x.due_date) if ok else None
        rows.append(ApRow(
            supplier_id=sid, name=xs[0].supplier, gstin=None, outstanding_paise=sum(x.outstanding_paise for x in ok),
            invoices=len(xs), disputed_paise=sum(x.outstanding_paise for x in xs if x.status == "rejected"),
            earliest_due=first.due_date if first else None, days_overdue=first.days_overdue if first else 0,
            statuses=sorted({x.status for x in xs}, key=lambda s: OPEN.index(s) if s in OPEN else 9),
            overdue=any(x.due_date < p.as_of for x in ok), due_week=any(p.as_of <= x.due_date <= week_end for x in ok),
        ))  # fmt: skip
    rows.sort(key=lambda r: -r.outstanding_paise)
    counts = {"all": len(rows), "overdue": sum(r.overdue for r in rows), "due_week": sum(r.due_week for r in rows),
              "pending_owner": sum("pending_owner" in r.statuses for r in rows),
              "pending_verif": sum("pending_verif" in r.statuses for r in rows),
              "scheduled": sum("scheduled" in r.statuses for r in rows)}  # fmt: skip
    executed = await _executed_between(session, p.start, p.as_of)
    overdue = [i for i in live if i.due_date < p.as_of]
    cards = ApCards(
        total_paise=sum(i.outstanding_paise for i in live), total_suppliers=len({i.supplier_id for i in live}),
        total_invoices=len(live), overdue_paise=sum(i.outstanding_paise for i in overdue),
        overdue_suppliers=len({i.supplier_id for i in overdue}),
        due_week_paise=sum(i.outstanding_paise for i in live if p.as_of <= i.due_date <= week_end),
        week_from=p.as_of, week_to=week_end, paid_paise=sum(executed), payments=len(executed),
    )  # fmt: skip
    if status and status != "all":
        rows = [
            r
            for r in rows
            if (getattr(r, status) if status in ("overdue", "due_week") else status in r.statuses)
        ]
    if q and q.strip():
        n = q.strip().lower()
        hit = {i.supplier_id for i in invs if n in i.number.lower() or n in (i.po_number or "").lower()
               or n in (i.grn or "").lower()}  # fmt: skip
        rows = [r for r in rows if n in r.name.lower() or r.supplier_id in hit]
    return ApOut(period=p, cards=cards, rows=rows, counts=counts)


async def _executed_between(session: AsyncSession, start: date, end: date) -> list[int]:
    q = select(SupplierPayment.amount_paise).where(SupplierPayment.status.in_(("executed", "confirmed")),
                                                   SupplierPayment.executed_on.between(start, end))  # fmt: skip
    return list((await session.execute(q)).scalars())


async def supplier(session: AsyncSession, supplier_id: uuid.UUID, month: str | None) -> ApSupplier:
    p = period(month)
    names = await purchasing.supplier_names(session, [supplier_id])
    if supplier_id not in names:
        raise NotFound("Supplier not found.")
    invs = await _load(session, p.as_of, supplier_id)
    invs.sort(key=lambda i: (i.status == "paid", i.due_date))
    return ApSupplier(supplier_id=supplier_id, name=names[supplier_id], gstin=None, period=p, invoices=invs,
                      interactions=await interactions_for(session, supplier_id=supplier_id, as_of=p.as_of))  # fmt: skip


async def one(session: AsyncSession, invoice_id: uuid.UUID) -> ApInvoice:
    out = await _load(session, clock.today(), ids=[invoice_id])
    if not out:
        raise NotFound("Supplier invoice not found.")
    return out[0]


# ---- workflow ------------------------------------------------------------------------------------------


async def _get(session: AsyncSession, invoice_id: uuid.UUID) -> SupplierInvoice:
    i = await session.get(SupplierInvoice, invoice_id, with_for_update=True)
    if i is None:
        raise NotFound("Supplier invoice not found.")
    return i


async def _step(session: AsyncSession, inv: SupplierInvoice, actor: uuid.UUID, action: str, to: str | None,
                note: str | None = None) -> None:  # fmt: skip
    """One step: the new status, the approval history row and the audit entry, together."""
    frm = inv.status
    if to is not None:
        inv.status = to
    session.add(PayableEvent(supplier_invoice_id=inv.id, action=action, from_status=frm, to_status=inv.status,
                             note=note, actor_id=actor))  # fmt: skip
    await audit.record(session, actor_id=actor, action="update", entity_type="supplier_invoice", entity_id=inv.id,
                       summary=f"{inv.number}: {action}" + (f" · {note}" if note else ""),
                       before={"status": frm}, after={"status": inv.status})  # fmt: skip
    await session.flush()
    if inv.deal_id:
        from app.billing import deals

        await deals.refresh_status(session, inv.deal_id)


async def create(session: AsyncSession, actor: uuid.UUID, body: SupplierInvoiceIn) -> ApInvoice:
    """A supplier invoice arrives (entered by accounts): linked to its PO and the purchase deal."""
    po = (await purchasing.po_facts(session, [body.po_id])).get(body.po_id)
    if po is None:
        raise NotFound("Purchase order not found.")
    if po["status"] in ("awaiting_approval", "cancelled"):
        raise DomainError(f"{po['number']} isn't an approved PO, so there is nothing to bill against.")
    number = body.number.strip()
    dup = (await session.execute(select(SupplierInvoice.id).where(
        SupplierInvoice.supplier_id == po["supplier_id"], SupplierInvoice.number == number))).scalar_one_or_none()  # fmt: skip
    if dup is not None:
        raise Conflict(
            f"Invoice {number} from {po['supplier']} is already recorded.", details={"id": str(dup)}
        )
    if body.invoice_date > clock.today():
        raise DomainError("The invoice date can't be in the future.")
    taxable = int((body.quantity * body.rate_paise).quantize(Decimal(1), ROUND_HALF_UP))
    gst = int((Decimal(taxable) * body.gst_rate / 100).quantize(Decimal(1), ROUND_HALF_UP))
    from app.billing import deals

    deal = await deals.deal_for_po(session, body.po_id)
    inv = SupplierInvoice(
        supplier_id=po["supplier_id"], po_id=body.po_id, deal_id=deal.id if deal else None, number=number,
        invoice_date=body.invoice_date, due_date=body.due_date or body.invoice_date + timedelta(days=30),
        quantity=body.quantity, rate_paise=body.rate_paise, taxable_paise=taxable, gst_paise=gst,
        total_paise=taxable + gst, supplier_gstin=body.supplier_gstin, note=body.note, created_by=actor,
        status="pending_verif",
    )  # fmt: skip
    session.add(inv)
    await session.flush()
    m = match(inv, po)
    inv.match = {"lines": [x.model_dump() for x in m], "ok": all(x.ok for x in m)}
    await _step(session, inv, actor, "Invoice received", None,
                None if inv.match["ok"] else "Three-way match: " + "; ".join(x.text for x in m if not x.ok))  # fmt: skip
    await events.emit(
        session, "supplier_invoice.received", {"id": str(inv.id), "number": number, "po": po["number"]}
    )
    if not inv.match["ok"]:
        await events.emit(session, "three_way_match.failed", {"id": str(inv.id), "number": number})
    return await one(session, inv.id)


async def verify(session: AsyncSession, actor: uuid.UUID, invoice_id: uuid.UUID) -> ApInvoice:
    """Accounts verification: the three-way match must be clean (checked again now)."""
    inv = await _get(session, invoice_id)
    if inv.status != "pending_verif":
        raise DomainError("Only an invoice waiting for verification can be verified.")
    po = (await purchasing.po_facts(session, [inv.po_id])).get(inv.po_id) if inv.po_id else None
    m = match(inv, po)
    if not all(x.ok for x in m):
        raise DomainError("Three-way match doesn't agree: " + "; ".join(x.text for x in m if not x.ok),
                          details={"mismatch": [x.text for x in m if not x.ok]})  # fmt: skip
    inv.match = {"lines": [x.model_dump() for x in m], "ok": True}
    inv.verified_by = actor
    await _step(session, inv, actor, "Verified by accounts", "pending_owner", "Three-way match agrees")
    return await one(session, inv.id)


async def approve(session: AsyncSession, actor: uuid.UUID, invoice_id: uuid.UUID) -> ApInvoice:
    """Owner approval: a decision. It doesn't touch payments or the outstanding amount."""
    inv = await _get(session, invoice_id)
    if inv.status != "pending_owner":
        raise DomainError("Only a verified invoice waiting for the owner can be approved.")
    inv.approved_by = actor
    await _step(session, inv, actor, "Approved by owner", "approved")
    await events.emit(session, "payable.approved", {"id": str(inv.id), "number": inv.number})
    return await one(session, inv.id)


async def schedule(
    session: AsyncSession, actor: uuid.UUID, invoice_id: uuid.UUID, body: ScheduleIn
) -> ApInvoice:
    """A plan to pay: never reduces the outstanding amount."""
    inv = await _get(session, invoice_id)
    if inv.status not in ("approved", "scheduled"):
        raise DomainError("Only an owner-approved invoice can be scheduled.")
    if body.scheduled_for < clock.today():
        raise DomainError("A payment can't be scheduled in the past.")
    cur = await one(session, inv.id)
    room = cur.outstanding_paise - cur.scheduled_paise
    if body.amount_paise > room:
        raise DomainError(f"Only {inr(room)} is left to schedule on {inv.number}.")
    p = SupplierPayment(supplier_invoice_id=inv.id, amount_paise=body.amount_paise, scheduled_for=body.scheduled_for,
                        scheduled_by=actor)  # fmt: skip
    session.add(p)
    await session.flush()
    await _step(session, inv, actor, "Payment scheduled", "scheduled",
                f"{inr(body.amount_paise)} on {body.scheduled_for:%-d %b %Y}")  # fmt: skip
    await events.emit(session, "payable.scheduled", {"id": str(inv.id), "payment": str(p.id)})
    return await one(session, inv.id)


async def _payment(session: AsyncSession, payment_id: uuid.UUID) -> tuple[SupplierPayment, SupplierInvoice]:
    p = await session.get(SupplierPayment, payment_id, with_for_update=True)
    if p is None:
        raise NotFound("Payment not found.")
    inv = await _get(session, p.supplier_invoice_id)
    return p, inv


async def execute(session: AsyncSession, actor: uuid.UUID, is_owner: bool, payment_id: uuid.UUID,
                  body: ExecuteIn) -> ApInvoice:  # fmt: skip
    """Sent from the bank (UTR). Counts only once the bank statement confirms it."""
    p, inv = await _payment(session, payment_id)
    if p.status != "scheduled" or inv.status != "scheduled":
        raise DomainError("Only a scheduled payment of an approved invoice can be executed.")
    if body.executed_on > clock.today():
        raise DomainError("A payment can't be executed in the future.")
    if inv.approved_by == actor:  # segregation of duties: the approver doesn't also send the money
        if not is_owner or not (body.override_reason or "").strip():
            raise DomainError("The person who approved this payment can't also execute it. The owner may override "
                              "this with a reason (it is logged).")  # fmt: skip
        p.override_reason = body.override_reason
    utr = body.utr.strip()
    dup = (
        await session.execute(select(SupplierPayment.id).where(SupplierPayment.utr == utr))
    ).scalar_one_or_none()
    if dup is not None:
        raise Conflict(f"UTR {utr} is already used by another payment.")
    p.status, p.utr, p.executed_on, p.executed_by = "executed", utr, body.executed_on, actor
    await _step(session, inv, actor, "Payment executed", None,
                f"{inr(p.amount_paise)} · UTR {utr}" + (f" · owner override: {p.override_reason}" if p.override_reason else ""))  # fmt: skip
    await events.emit(session, "payment.executed", {"id": str(p.id), "utr": utr})
    return await one(session, inv.id)


async def bank_confirm(
    session: AsyncSession, actor: uuid.UUID, payment_id: uuid.UUID, body: BankConfirmIn
) -> ApInvoice:
    """The bank statement line matches the payment (amount, UTR, date): only now it is paid."""
    p, inv = await _payment(session, payment_id)
    if p.status == "confirmed":
        return await one(session, inv.id)  # the same bank line twice: one effect
    if p.status != "executed":
        raise DomainError("Only an executed payment can be confirmed by the bank.")
    if body.utr.strip() != p.utr or body.amount_paise != p.amount_paise:
        raise DomainError("The bank line doesn't match this payment (UTR and amount must agree).")
    if p.executed_on and body.confirmed_on < p.executed_on:
        raise DomainError("The bank can't confirm before the payment was sent.")
    p.status, p.confirmed_on, p.confirmed_by = "confirmed", body.confirmed_on, actor
    paid = sum(x.amount_paise for x in (await session.execute(select(SupplierPayment).where(
        SupplierPayment.supplier_invoice_id == inv.id, SupplierPayment.status == "confirmed"))).scalars())  # fmt: skip
    await _step(session, inv, actor, "Bank confirmed", "paid" if paid >= inv.total_paise else None,
                f"{inr(p.amount_paise)} · UTR {p.utr}")  # fmt: skip
    await events.emit(session, "payment.bank_confirmed", {"id": str(p.id), "utr": p.utr})
    return await one(session, inv.id)


async def hold_or_reject(session: AsyncSession, actor: uuid.UUID, invoice_id: uuid.UUID, action: str,
                         reason: str) -> ApInvoice:  # fmt: skip
    inv = await _get(session, invoice_id)
    if inv.status not in OPEN and not (action == "reject" and inv.status == "on_hold"):
        raise DomainError("Only an open invoice can be held or rejected.")
    pays = list(
        (
            await session.execute(
                select(SupplierPayment).where(SupplierPayment.supplier_invoice_id == inv.id)
            )
        ).scalars()
    )
    if any(p.status == "executed" for p in pays):
        raise DomainError("A payment has already been sent; wait for the bank to confirm it first.")
    for p in pays:
        if p.status == "scheduled":
            p.status = "cancelled"
    inv.hold_reason = reason
    await _step(session, inv, actor, "Put on hold" if action == "hold" else "Rejected",
                "on_hold" if action == "hold" else "rejected", reason)  # fmt: skip
    return await one(session, inv.id)


async def release(session: AsyncSession, actor: uuid.UUID, invoice_id: uuid.UUID, reason: str) -> ApInvoice:
    """Release a hold: back to the owner's approval (never straight to scheduled)."""
    inv = await _get(session, invoice_id)
    if inv.status != "on_hold":
        raise DomainError("Only an invoice on hold can be released.")
    inv.hold_reason = None
    await _step(session, inv, actor, "Hold released", "pending_owner", reason)
    return await one(session, inv.id)


async def export_csv(session: AsyncSession, actor: uuid.UUID, month: str | None, q: str | None,
                     status: str | None) -> str:  # fmt: skip
    out = await payables(session, month, q, status)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(
        [
            "Supplier",
            "Outstanding (Rs)",
            "Invoices",
            "Disputed (Rs)",
            "Earliest due",
            "Days overdue",
            "Statuses",
        ]
    )
    for r in out.rows:
        w.writerow([r.name, f"{r.outstanding_paise / 100:.2f}", r.invoices, f"{r.disputed_paise / 100:.2f}",
                    r.earliest_due or "", r.days_overdue, " ".join(r.statuses)])  # fmt: skip
    await audit.record(session, actor_id=actor, action="export", entity_type="payables", entity_id=None,
                       summary=f"Payables exported · {out.period.month} · {len(out.rows)} rows")  # fmt: skip
    return buf.getvalue()


async def monthly_totals(session: AsyncSession, start: date, end: date) -> dict[str, dict[str, int]]:
    """Per month: supplier bills received (by invoice date, rejected ones left out) and supplier money that
    actually left the bank (bank-confirmed payments, by confirmation date)."""
    month = func.to_char(SupplierInvoice.invoice_date, "YYYY-MM")
    billed = (await session.execute(
        select(month, func.sum(SupplierInvoice.total_paise))
        .where(SupplierInvoice.invoice_date.between(start, end), SupplierInvoice.status != "rejected").group_by(month)
    )).all()  # fmt: skip
    pmonth = func.to_char(SupplierPayment.confirmed_on, "YYYY-MM")
    paid = (await session.execute(
        select(pmonth, func.sum(SupplierPayment.amount_paise))
        .where(SupplierPayment.status == "confirmed", SupplierPayment.confirmed_on.between(start, end)).group_by(pmonth)
    )).all()  # fmt: skip
    out: dict[str, dict[str, int]] = {}
    for m, v in billed:
        out.setdefault(m, {})["payables"] = int(v or 0)
    for m, v in paid:
        out.setdefault(m, {})["paid"] = int(v or 0)
    return out
