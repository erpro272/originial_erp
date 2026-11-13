"""Customers: master data, period metrics, health, follow-ups, merge."""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import audit, clock, keys
from app.core.crypto import mask_tail
from app.core.errors import Conflict, DomainError, NotFound
from app.core.gst import STATE_CODES, gstin_errors, pan_errors, pan_from_gstin, state_code_from_gstin
from app.core.models import User
from app.core.services import kv
from app.customers import health as health_rules
from app.customers.models import Customer, CustomerAddress, CustomerContact, CustomerFollowup
from app.customers.schemas import (
    AddressOut,
    ContactOut,
    CustomerDetail,
    CustomerIn,
    CustomerPage,
    CustomerPatch,
    CustomerRow,
    FollowupIn,
    FollowupOut,
    HealthSettings,
    InvoiceBrief,
    MonthPoint,
    Overview,
    Period,
    ProductBought,
)
from app.invoices import stats

HEALTH_KEY = "customer-health"


# ---- period ---------------------------------------------------------------------------------


def resolve_period(preset: str, date_from: date | None, date_to: date | None, today: date) -> Period:
    if preset == "custom":
        if not date_from or not date_to or date_from > date_to:
            raise DomainError("Choose a valid date range (from must be on or before to).")
        start, end = date_from, date_to
    elif preset == "this_month":
        start, end = today.replace(day=1), today
    elif preset == "this_quarter":
        fy_start_month = 4
        q_index = ((today.month - fy_start_month) % 12) // 3
        month = (fy_start_month + q_index * 3 - 1) % 12 + 1
        year = today.year if month <= today.month else today.year - 1
        start, end = date(year, month, 1), today
    elif preset == "last_12_months":
        start, end = today - timedelta(days=364), today
    else:  # fytd
        start, end = date(today.year if today.month >= 4 else today.year - 1, 4, 1), today
    length = (end - start).days + 1
    return Period(preset=preset, date_from=start, date_to=end,
                  prev_from=start - timedelta(days=length), prev_to=start - timedelta(days=1))  # fmt: skip


async def get_health_settings(session: AsyncSession) -> HealthSettings:
    try:
        return HealthSettings.model_validate(await kv.get_setting(session, HEALTH_KEY))
    except (NotFound, ValueError):
        return HealthSettings()


async def put_health_settings(session: AsyncSession, actor: uuid.UUID, s: HealthSettings) -> HealthSettings:
    if s.inactive_days >= s.dormant_days:
        raise DomainError("Inactive days must be fewer than dormant days.")
    await kv.put_setting(session, actor, HEALTH_KEY, s.model_dump())
    return s


# ---- listing --------------------------------------------------------------------------------


@dataclass
class CustomerFilters:
    q: str | None = None
    health: list[str] = field(default_factory=list)
    state_codes: list[str] = field(default_factory=list)
    product: str | None = None
    outstanding_only: bool = False
    min_sales_paise: int | None = None
    max_sales_paise: int | None = None
    tiers: list[str] = field(default_factory=list)
    followups_due: bool = False


FIELD_COUNT = len(CustomerRow.model_fields)


async def _rows(session: AsyncSession, period: Period) -> list[CustomerRow]:
    today = clock.today()
    cfg = await get_health_settings(session)
    st = await stats.customer_stats(
        session, period.date_from, period.date_to, period.prev_from, period.prev_to
    )
    customers = list(
        (await session.execute(select(Customer).where(Customer.merged_into_id.is_(None)))).scalars()
    )
    billing_city: dict[uuid.UUID, str | None] = {
        cid: city
        for cid, city in await session.execute(
            select(CustomerAddress.customer_id, CustomerAddress.city).where(CustomerAddress.kind == "billing")
        )
    }
    contact: dict[uuid.UUID, str] = {}
    for cid, name, _primary in await session.execute(
        select(CustomerContact.customer_id, CustomerContact.name, CustomerContact.is_primary).order_by(
            CustomerContact.is_primary.desc()
        )
    ):
        contact.setdefault(cid, name)
    fu: dict[uuid.UUID, tuple[int, date | None]] = {
        cid: (n, d)
        for cid, n, d in await session.execute(
            select(CustomerFollowup.customer_id, func.count(), func.min(CustomerFollowup.due_date))
            .where(CustomerFollowup.done_at.is_(None), CustomerFollowup.kind == "reminder")
            .group_by(CustomerFollowup.customer_id)
        )
    }
    hv = health_rules.high_value_threshold([s.period_sales for s in st.values()], cfg.high_value_top_pct)
    rows = []
    for c in customers:
        s = st.get(c.id, stats.CustomerStats())
        tags = health_rules.health_tags(
            s if s.invoices_all else None, cfg, today, period.date_from, period.date_to, hv
        )
        freq = None
        if s.invoices_all >= 2 and s.first_date and s.last_date:
            freq = round((s.last_date - s.first_date).days / (s.invoices_all - 1), 1)
        rows.append(
            CustomerRow(
                id=c.id, name=c.name, gstin=c.gstin, pan=c.pan, state_code=c.state_code,
                state=STATE_CODES.get(c.state_code or ""), city=billing_city.get(c.id),
                phone=c.phone, email=c.email, tier=c.tier, tags=c.tags or [],
                payment_terms_days=c.payment_terms_days, credit_limit_paise=c.credit_limit_paise,
                source=c.source, created_at=c.created_at, primary_contact=contact.get(c.id),
                total_sales_paise=s.period_sales, invoices=s.period_invoices,
                aov_paise=round(s.period_sales / s.period_invoices) if s.period_invoices else None,
                units_sold=s.period_units, previous_sales_paise=s.prev_sales,
                sales_change_pct=round((s.period_sales - s.prev_sales) / s.prev_sales * 100, 1)
                if s.prev_sales else None,
                outstanding_paise=s.outstanding, last_purchase=s.last_date,
                days_since_last=(today - s.last_date).days if s.last_date else None,
                first_purchase=s.first_date, frequency_days=freq, lifetime_sales_paise=s.lifetime_sales,
                lifetime_invoices=s.invoices_all,
                credit_used_pct=round(s.outstanding / c.credit_limit_paise * 100, 1)
                if c.credit_limit_paise else None,
                open_followups=fu.get(c.id, (0, None))[0], next_followup=fu.get(c.id, (0, None))[1],
                health=health_rules.primary(tags), health_tags=tags,
            )
        )  # fmt: skip
    return rows


_SORT: dict[str, Any] = {
    "name": lambda r: r.name.lower(),
    "total_sales": lambda r: r.total_sales_paise,
    "invoices": lambda r: r.invoices,
    "aov": lambda r: r.aov_paise or 0,
    "units": lambda r: r.units_sold,
    "outstanding": lambda r: r.outstanding_paise,
    "last_purchase": lambda r: r.last_purchase or date.min,
    "frequency": lambda r: r.frequency_days if r.frequency_days is not None else 10**9,
    "health": lambda r: health_rules.PRIMARY_ORDER.index(r.health) if r.health else 99,
    "state": lambda r: r.state or "",
    "created": lambda r: r.created_at,
}


async def list_customers(
    session: AsyncSession, period: Period, f: CustomerFilters, sort: str = "total_sales",
    desc: bool = True, limit: int = 8, offset: int = 0,
) -> CustomerPage:  # fmt: skip
    rows = await _rows(session, period)
    overview = Overview(
        total_customers=len(rows),
        active_customers=sum(r.invoices > 0 for r in rows),
        active_pct=round(sum(r.invoices > 0 for r in rows) / len(rows) * 100, 1) if rows else 0.0,
        new_customers=sum("new" in r.health_tags for r in rows),
        units_sold=sum((r.units_sold for r in rows), Decimal(0)),
    )
    counts = {"all": len(rows)} | {
        h: sum(h in r.health_tags for r in rows) for h in health_rules.PRIMARY_ORDER
    }
    items = rows
    if f.q:
        q = f.q.strip().lower()
        digits = "".join(ch for ch in q if ch.isdigit())
        items = [r for r in items if q in r.name.lower() or q.upper() in (r.gstin or "")
                 or (digits and len(digits) >= 4 and digits in "".join(ch for ch in (r.phone or "") if ch.isdigit()))]  # fmt: skip
    if f.health:
        items = [r for r in items if set(f.health) & set(r.health_tags)]
    if f.state_codes:
        items = [r for r in items if r.state_code in f.state_codes]
    if f.tiers:
        items = [r for r in items if r.tier in f.tiers]
    if f.outstanding_only:
        items = [r for r in items if r.outstanding_paise > 0]
    if f.min_sales_paise is not None:
        items = [r for r in items if r.total_sales_paise >= f.min_sales_paise]
    if f.max_sales_paise is not None:
        items = [r for r in items if r.total_sales_paise <= f.max_sales_paise]
    if f.followups_due:
        items = [r for r in items if r.next_followup and r.next_followup <= clock.today()]
    if f.product:
        bought = await stats.customers_who_bought(session, f.product)
        items = [r for r in items if r.id in bought]
    items.sort(key=lambda r: r.name.lower())
    items.sort(key=_SORT.get(sort, _SORT["total_sales"]), reverse=desc)
    return CustomerPage(items=items[offset : offset + limit], total=len(items), limit=limit, offset=offset,
                        period=period, overview=overview, health_counts=counts,
                        available_fields=FIELD_COUNT)  # fmt: skip


# ---- detail ---------------------------------------------------------------------------------


async def _followups(session: AsyncSession, customer_id: uuid.UUID) -> list[FollowupOut]:
    rows = await session.execute(
        select(CustomerFollowup, User.full_name)
        .outerjoin(User, User.id == CustomerFollowup.created_by)
        .where(CustomerFollowup.customer_id == customer_id)
        .order_by(CustomerFollowup.created_at.desc())
    )
    return [
        FollowupOut(id=f.id, kind=f.kind, note=f.note, due_date=f.due_date, done_at=f.done_at,
                    created_at=f.created_at, created_by_name=name)
        for f, name in rows
    ]  # fmt: skip


async def get_detail(
    session: AsyncSession, customer_id: uuid.UUID, period: Period, can_see_sensitive: bool
) -> CustomerDetail:
    c = await session.get(Customer, customer_id)
    if c is None:
        raise NotFound("Customer not found.")
    rows = [r for r in await _rows(session, period) if r.id == customer_id]
    if not rows:  # merged-away customer: still viewable, without metrics
        raise NotFound(
            "This customer was merged into another record.", details={"merged_into_id": str(c.merged_into_id)}
        )
    cipher = await keys.get_cipher(session, c.tenant_id)
    account = cipher.decrypt(c.bank_account_enc, "bank_account") if c.bank_account_enc else None
    upi = cipher.decrypt(c.upi_enc, "upi_id") if c.upi_enc else None
    addrs = (
        await session.execute(select(CustomerAddress).where(CustomerAddress.customer_id == c.id))
    ).scalars()
    contacts = (
        await session.execute(
            select(CustomerContact)
            .where(CustomerContact.customer_id == c.id)
            .order_by(CustomerContact.is_primary.desc())
        )
    ).scalars()
    invoices = await stats.customer_invoices(session, c.id)
    today = clock.today()
    since = date(today.year - 1, today.month, 1)
    return CustomerDetail(
        row=rows[0],
        addresses=[AddressOut.model_validate(a, from_attributes=True) for a in addrs],
        contacts=[ContactOut.model_validate(x, from_attributes=True) for x in contacts],
        notes=c.notes, bank_name=c.bank_name, bank_ifsc=c.bank_ifsc,
        bank_account=account if can_see_sensitive else mask_tail(account),
        upi_id=upi if can_see_sensitive else _mask_upi(upi),
        sensitive_visible=can_see_sensitive,
        followups=await _followups(session, c.id),
        invoices=[
            InvoiceBrief(
                id=i.id, invoice_number=i.invoice_number, invoice_date=i.invoice_date,
                grand_total_paise=i.grand_total_paise, balance_due_paise=i.balance_due_paise,
                status="paid" if not i.balance_due_paise else
                ("partial" if (i.balance_due_paise or 0) < (i.grand_total_paise or 0) else "unpaid"),
                source=i.source, upload_id=i.upload_id,
            )
            for i in invoices
        ],
        monthly_sales=[MonthPoint(month=m, sales_paise=v) for m, v in await stats.monthly_sales(session, c.id, since)],
        top_products=[ProductBought(**p) for p in await stats.top_products(session, c.id)],
        merged_into_id=c.merged_into_id,
    )  # fmt: skip


def _mask_upi(upi: str | None) -> str | None:
    if not upi or "@" not in upi:
        return mask_tail(upi)
    handle, bank = upi.split("@", 1)
    return f"{mask_tail(handle, visible=2)}@{bank}"


# ---- writes ---------------------------------------------------------------------------------


def validate_identity(
    gstin: str | None, pan: str | None, state_code: str | None
) -> tuple[str | None, str | None]:
    """Returns (pan, state_code) filled from the GSTIN. Raises with field errors."""
    errors: dict[str, str] = {}
    if gstin and (e := gstin_errors(gstin)):
        errors["gstin"] = e[0]
    if pan and (e := pan_errors(pan)):
        errors["pan"] = e[0]
    if gstin and not errors.get("gstin"):
        if pan and pan != pan_from_gstin(gstin):
            errors["pan"] = f"PAN doesn't match the GSTIN (GSTIN contains {pan_from_gstin(gstin)})."
        if state_code and state_code != state_code_from_gstin(gstin):
            errors["state_code"] = (
                f"State doesn't match the GSTIN (GSTIN is for state {state_code_from_gstin(gstin)})."
            )
        pan = pan or pan_from_gstin(gstin)
        state_code = state_code or state_code_from_gstin(gstin)
    if state_code and state_code not in STATE_CODES:
        errors["state_code"] = "Unknown state code."
    if errors:
        raise DomainError("Please fix the highlighted fields.", details={"fields": errors})
    return pan, state_code


async def _check_gstin_unique(session: AsyncSession, gstin: str | None, exclude: uuid.UUID | None) -> None:
    if not gstin:
        return
    q = select(Customer.id, Customer.name).where(Customer.gstin == gstin, Customer.merged_into_id.is_(None))
    if exclude:
        q = q.where(Customer.id != exclude)
    existing = (await session.execute(q)).first()
    if existing:
        raise Conflict(
            f"{existing.name} already has this GSTIN.",
            details={
                "fields": {"gstin": "Already used by another customer."},
                "customer_id": str(existing.id),
            },
        )


def _snapshot(c: Customer) -> dict[str, Any]:
    return {k: getattr(c, k) for k in ("name", "gstin", "pan", "state_code", "phone", "email", "payment_terms_days",
                                       "credit_limit_paise", "tier", "tags", "notes", "bank_name", "bank_ifsc",
                                       "is_active")} | {"bank_account": "set" if c.bank_account_enc else None}  # fmt: skip


async def _set_children(
    session: AsyncSession, c: Customer, addresses: list[Any] | None, contacts: list[Any] | None
) -> None:
    if addresses is not None:
        await session.execute(delete(CustomerAddress).where(CustomerAddress.customer_id == c.id))
        for a in addresses:
            session.add(CustomerAddress(customer_id=c.id, **a.model_dump()))
    if contacts is not None:
        await session.execute(delete(CustomerContact).where(CustomerContact.customer_id == c.id))
        for x in contacts:
            session.add(CustomerContact(customer_id=c.id, **x.model_dump()))


async def create_customer(
    session: AsyncSession, actor: uuid.UUID, body: CustomerIn, source: str = "manual"
) -> Customer:
    pan, state = validate_identity(body.gstin, body.pan, body.state_code)
    await _check_gstin_unique(session, body.gstin, None)
    data = body.model_dump(exclude={"addresses", "contacts", "bank_account", "upi_id", "pan", "state_code"})
    c = Customer(**data, pan=pan, state_code=state, source=source)
    session.add(c)
    await session.flush()
    await _set_sensitive(session, c, body.bank_account, body.upi_id)
    await _set_children(session, c, body.addresses, body.contacts)
    try:
        await session.flush()
    except IntegrityError as exc:  # race on the unique GSTIN index
        raise Conflict("Another customer already has this GSTIN.") from exc
    await audit.record(session, actor_id=actor, action="create", entity_type="customer", entity_id=c.id,
                       summary=f"Customer '{c.name}' created", after=_snapshot(c))  # fmt: skip
    return c


async def _set_sensitive(session: AsyncSession, c: Customer, account: str | None, upi: str | None) -> None:
    cipher = await keys.get_cipher(session, c.tenant_id)
    if account is not None:
        c.bank_account_enc = cipher.encrypt(account, "bank_account") if account else None
        c.bank_account_last4 = account[-4:] if account else None
    if upi is not None:
        c.upi_enc = cipher.encrypt(upi, "upi_id") if upi else None


async def update_customer(
    session: AsyncSession, actor: uuid.UUID, cid: uuid.UUID, body: CustomerPatch
) -> Customer:
    c = await session.get(Customer, cid, with_for_update=True)
    if c is None or c.merged_into_id:
        raise NotFound("Customer not found.")
    before = _snapshot(c)
    data = body.model_dump(exclude_unset=True)
    gstin = data.get("gstin", c.gstin)
    pan, state = validate_identity(gstin, data.get("pan", c.pan if "gstin" not in data else None),
                                   data.get("state_code", c.state_code if "gstin" not in data else None))  # fmt: skip
    await _check_gstin_unique(session, gstin, c.id)
    for k, v in data.items():
        if k in ("addresses", "contacts", "bank_account", "upi_id", "pan", "state_code"):
            continue
        setattr(c, k, v)
    c.pan, c.state_code = pan, state
    await _set_sensitive(session, c, data.get("bank_account"), data.get("upi_id"))
    await _set_children(session, c, body.addresses if "addresses" in data else None,
                        body.contacts if "contacts" in data else None)  # fmt: skip
    b, a = audit.diff(before, _snapshot(c))
    if a or "addresses" in data or "contacts" in data:
        await audit.record(session, actor_id=actor, action="update", entity_type="customer", entity_id=c.id,
                           summary=f"Customer '{c.name}' updated", before=b, after=a)  # fmt: skip
    return c


async def merge(
    session: AsyncSession, actor: uuid.UUID, target_id: uuid.UUID, source_id: uuid.UUID
) -> Customer:
    """Merge a duplicate (source) into target: invoices, orders, contacts, follow-ups move over."""
    from app.orders import service as orders

    if target_id == source_id:
        raise DomainError("Choose two different customers to merge.")
    target = await session.get(Customer, target_id, with_for_update=True)
    source = await session.get(Customer, source_id, with_for_update=True)
    if not target or not source or target.merged_into_id or source.merged_into_id:
        raise NotFound("Customer not found.")
    if target.gstin and source.gstin and target.gstin != source.gstin:
        raise DomainError("These customers have different GSTINs, so they are different businesses.")
    moved_inv = await stats.reassign_customer(session, source.id, target.id)
    moved_ord = await orders.reassign_customer(session, source.id, target.id)
    await session.execute(
        update(CustomerContact).where(CustomerContact.customer_id == source.id).values(customer_id=target.id)
    )
    await session.execute(
        update(CustomerFollowup)
        .where(CustomerFollowup.customer_id == source.id)
        .values(customer_id=target.id)
    )
    if not target.gstin and source.gstin:
        gstin, source.gstin = source.gstin, None
        await session.flush()
        target.gstin, target.pan, target.state_code = gstin, source.pan, source.state_code
    for k in ("phone", "email", "payment_terms_days", "credit_limit_paise"):
        if getattr(target, k) is None:
            setattr(target, k, getattr(source, k))
    target.tags = sorted(set(target.tags or []) | set(source.tags or []))
    source.merged_into_id, source.is_active = target.id, False
    await audit.record(session, actor_id=actor, action="merge", entity_type="customer", entity_id=target.id,
                       summary=f"'{source.name}' merged into '{target.name}' "
                               f"({moved_inv} invoices, {moved_ord} orders moved)",
                       before={"source_id": str(source.id)}, after={"target_id": str(target.id)})  # fmt: skip
    return target


async def add_followup(
    session: AsyncSession, actor: uuid.UUID, cid: uuid.UUID, body: FollowupIn
) -> FollowupOut:
    c = await session.get(Customer, cid)
    if c is None:
        raise NotFound("Customer not found.")
    if body.kind == "reminder" and not body.due_date:
        raise DomainError("A reminder needs a due date.", details={"fields": {"due_date": "Required"}})
    f = CustomerFollowup(customer_id=cid, kind=body.kind, note=body.note, due_date=body.due_date,
                         assigned_to=body.assigned_to or actor, created_by=actor,
                         done_at=None if body.kind == "reminder" else datetime.now(UTC))  # fmt: skip
    session.add(f)
    await session.flush()
    await audit.record(session, actor_id=actor, action="create", entity_type="followup", entity_id=f.id,
                       summary=f"{body.kind.title()} logged for '{c.name}'")  # fmt: skip
    return next(x for x in await _followups(session, cid) if x.id == f.id)


async def complete_followup(session: AsyncSession, actor: uuid.UUID, cid: uuid.UUID, fid: uuid.UUID) -> None:
    f = await session.get(CustomerFollowup, fid)
    if f is None or f.customer_id != cid:
        raise NotFound("Follow-up not found.")
    f.done_at = datetime.now(UTC)
    await audit.record(session, actor_id=actor, action="update", entity_type="followup", entity_id=f.id,
                       summary="Reminder marked done")  # fmt: skip


async def find_by_gstin(session: AsyncSession, gstin: str) -> Customer | None:
    return (
        await session.execute(
            select(Customer).where(Customer.gstin == gstin, Customer.merged_into_id.is_(None))
        )
    ).scalar_one_or_none()


async def active_customers(session: AsyncSession) -> list[Customer]:
    return list((await session.execute(select(Customer).where(Customer.merged_into_id.is_(None)))).scalars())
