"""Executive Dashboard: reads the other modules through their service functions and summarises them.
It stores nothing and schedules nothing: the Gantt and machine load mirror Planning, cash flow mirrors Billing."""

import uuid
from datetime import date, timedelta
from decimal import Decimal
from statistics import mean
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.billing import payables as ap
from app.billing import receivables as ar
from app.core import clock
from app.core.errors import DomainError
from app.customers import service as customers
from app.dashboard.schemas import (
    Alert,
    CashMonth,
    CustomerHealth,
    DashboardOut,
    DelayedOrder,
    Kpi,
    Kpis,
    MachineDay,
    MachineLoad,
    MachineOrder,
    PlanRef,
    Range,
    Timeline,
    TimelineRow,
    TopCustomer,
)
from app.invoices import ledger
from app.orders import service as orders
from app.orders.schemas import OrderOut
from app.planning import service as planning
from app.purchasing import service as purchasing

MAX_DAYS = 92
TONE_ORDER = {"hi": 0, "md": 1, "bl": 2, "ok": 3}
SOURCE_ORDER = {"planning": 0, "orders": 1, "production": 2, "purchasing": 3, "billing": 4}


def default_range(today: date) -> tuple[date, date]:
    """This week and next (Monday to Saturday)."""
    monday = today - timedelta(days=today.weekday())
    return monday, monday + timedelta(days=12)


def resolve_range(start: date | None, end: date | None, today: date) -> Range:
    d0, d1 = default_range(today)
    start, end = start or d0, end or (start + timedelta(days=12) if start else d1)
    if end < start:
        raise DomainError("The end date is before the start date.", details={"field": "to"})
    if (end - start).days + 1 > MAX_DAYS:
        raise DomainError(f"Choose at most {MAX_DAYS} days.", details={"field": "to"})
    return Range(
        start=start, end=end, days=[start + timedelta(i) for i in range((end - start).days + 1)], today=today
    )


def _d(x: Any) -> date:
    return x if isinstance(x, date) else date.fromisoformat(str(x))


def _short(d: date) -> str:
    return f"{d.day} {d:%b}"


def _qty(q: Decimal) -> str:
    return f"{q.normalize():f}" if q == q.to_integral() else f"{q:.1f}"


def _due(o: OrderOut) -> date:
    return o.promised_date or o.ship_date


async def _names(
    session: AsyncSession, ids: set[str], open_by_id: dict[str, OrderOut]
) -> dict[str, tuple[str, str, str, int | None, date | None]]:
    """order id -> (number, customer, status, progress, due) for schedule rows (closed orders too)."""
    out: dict[str, tuple[str, str, str, int | None, date | None]] = {
        i: (o.number, o.customer_name, str(o.status), o.progress_pct, _due(o))
        for i, o in open_by_id.items()
        if i in ids
    }
    rest = [uuid.UUID(i) for i in ids - set(out)]
    if rest:
        facts = await orders.facts(session, rest)
        names = await customers.briefs(session, list({f["customer_id"] for f in facts.values()}))
        for oid, f in facts.items():
            out[str(oid)] = (f["number"], names.get(f["customer_id"], {}).get("name", "—"), f["status"],
                             f["progress_pct"], f["promised_date"] or f["ship_date"])  # fmt: skip
    return out


def _machines(
    sched: dict[str, Any], rng: Range, names: dict[str, tuple[str, str, str, int | None, date | None]]
) -> list[MachineLoad]:
    in_range = {d.isoformat() for d in rng.days}
    added = set(sched["added"])
    out = []
    for m in sched["load"]:
        days = [MachineDay(day=_d(k), current=v["current"], after=v["after"])
                for k, v in sorted(m["days"].items()) if k in in_range]  # fmt: skip
        work = [x for x in days if x.after is not None]
        peak = max(work, key=lambda x: x.after or 0, default=None)
        contrib = []
        for oid, per in sched["hours"].get(m["machine"], {}).items():
            h = round(sum(v for k, v in per.items() if k in in_range), 1)
            if h > 0:
                n = names.get(oid)
                contrib.append(MachineOrder(number=n[0] if n else "—", customer=n[1] if n else "—", hours=h,
                                            added=oid in added))  # fmt: skip
        contrib.sort(key=lambda c: (c.added, -c.hours))
        out.append(MachineLoad(
            machine=m["machine"], name=m["name"],
            current=round(mean(x.current or 0 for x in work)) if work else None,
            after=round(mean(x.after or 0 for x in work)) if work else None,
            peak_after=peak.after if peak else None, peak_day=peak.day if peak else None,
            over=bool(peak and (peak.after or 0) > 100), days=days, orders=contrib,
        ))  # fmt: skip
    return out


async def overview(session: AsyncSession, start: date | None, end: date | None) -> DashboardOut:
    today = clock.today()
    rng = resolve_range(start, end, today)
    sched = await planning.dashboard_schedule(session)
    open_ = await orders.open_orders(session)
    open_by_id = {str(o.id): o for o in open_}
    ids = {r["id"] for r in sched["rows"]} | {oid for per in sched["hours"].values() for oid in per}
    names = await _names(session, ids, open_by_id)

    # ---- Order Timeline (mirror of the schedule) + machine load
    rows: list[TimelineRow] = []
    finish_of: dict[str, date] = {}
    for r in sched["rows"]:
        s, f = _d(r["start"]), _d(r["finish"])
        finish_of[r["id"]] = f
        n = names.get(r["id"])
        if n is None or f < rng.start or s > rng.end:
            continue
        due = n[4]
        rows.append(TimelineRow(order_id=uuid.UUID(r["id"]), number=n[0], customer=n[1], status=n[2], start=s,
                                finish=f, due=due, progress_pct=n[3],
                                late=bool(due and n[2] not in ("completed", "shipped") and (f > due or due < today))))  # fmt: skip
    rows.sort(key=lambda x: (x.start, x.number))
    machines = _machines(sched, rng, names)
    plan = sched["plan"]
    draft = sched["draft"]
    timeline = Timeline(
        source=sched["source"],
        plan=PlanRef(id=plan["id"], number=plan["number"], approved_at=plan["approved_at"],
                     needs_reapproval=plan["needs_reapproval"]) if plan else None,
        draft=PlanRef(id=draft["id"], number=draft["number"], status=draft["status"],
                      orders=sorted(names[i][0] for i in draft["orders"] if i in names)) if draft else None,
        rows=rows, machines=machines,
    )  # fmt: skip

    # ---- KPIs
    daily = []
    for d in rng.days:
        vals = [x.current for m in machines for x in m.days if x.day == d and x.current is not None]
        if vals:
            daily.append(round(mean(vals), 1))
    util = Kpi(value=round(mean(daily)) if daily else None, unit="%", trend=daily,
               note=f"Average machine load, {len(daily)} working days" if daily else "No scheduled work in this range")  # fmt: skip
    making = [o for o in open_ if o.status == "in_production"]
    units = {o.unit for o in making}
    total = sum((o.quantity for o in making), Decimal(0))
    in_progress = (Kpi(value=float(total), unit=units.pop() if len(units) == 1 else "units",
                       note=f"{len(making)} order{'s' * (len(making) != 1)} in production")
                   if making and len(units) <= 1 else
                   Kpi(value=len(making), unit="orders", note="in production (mixed units)"))  # fmt: skip
    actual = await orders.cycle_days(session, today - timedelta(days=90))
    if actual:
        cycle = Kpi(value=round(mean(actual), 1), unit="days",
                    note=f"Actual · {len(actual)} order{'s' * (len(actual) != 1)} finished in the last 90 days")  # fmt: skip
    else:
        spans = [(_d(r["finish"]) - _d(r["start"])).days + 1 for r in sched["rows"]]
        cycle = Kpi(value=round(mean(spans), 1) if spans else None, unit="days",
                    note="Planned (no finished production recorded yet)" if spans else "No production data yet")  # fmt: skip
    delayed: list[DelayedOrder] = []
    for o in open_:
        due, fin = _due(o), finish_of.get(str(o.id))
        reason = (f"{(today - due).days} day{'s' * ((today - due).days != 1)} past the {_short(due)} due date"
                  if due < today else
                  f"Planned to finish {_short(fin)}, due {_short(due)}" if fin and fin > due else
                  o.signal.text if o.signal.kind == "behind" else None)  # fmt: skip
        if reason:
            delayed.append(
                DelayedOrder(id=o.id, number=o.number, customer=o.customer_name, due=due, reason=reason)
            )
    delayed.sort(key=lambda x: x.due)
    kpis = Kpis(utilization=util, in_progress=in_progress, cycle_time=cycle,
                delayed=Kpi(value=len(delayed), unit="orders", note="Open orders at risk of missing their date"),
                delayed_orders=delayed)  # fmt: skip

    # ---- Cash flow: the 6 months ending with the range
    first = date(rng.end.year, rng.end.month, 1)
    for _ in range(5):
        first = (first - timedelta(days=1)).replace(day=1)
    last = (date(rng.end.year, rng.end.month, 28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    sales, buys = (
        await ledger.monthly_totals(session, first, last),
        await ap.monthly_totals(session, first, last),
    )
    cash, m = [], first
    while m <= last:
        k = f"{m:%Y-%m}"
        s_, b_ = sales.get(k, {}), buys.get(k, {})
        cash.append(CashMonth(month=k, label=f"{m:%b}", invoiced=s_.get("invoiced", 0), collected=s_.get("collected", 0),
                              payables=b_.get("payables", 0), paid=b_.get("paid", 0)))  # fmt: skip
        m = (m + timedelta(days=32)).replace(day=1)

    # ---- Customer health (the Customers tab's own rules, financial year to date)
    period = customers.resolve_period("fytd", None, None, today)
    page = await customers.list_customers(session, period, customers.CustomerFilters(), limit=1)
    top = page.items[0] if page.items and page.items[0].total_sales_paise > 0 else None
    health = CustomerHealth(
        period_label=f"FY to date ({_short(period.date_from)} – {_short(period.date_to)})",
        high_value=page.health_counts.get("high_value", 0), repeat=page.health_counts.get("repeat", 0),
        inactive=page.health_counts.get("inactive", 0),
        top=TopCustomer(id=top.id, name=top.name, sales_paise=top.total_sales_paise) if top else None,
        total_orders=await orders.received_between(session, period.date_from, period.date_to),
    )  # fmt: skip

    alerts = await _alerts(session, timeline, delayed, today)
    return DashboardOut(
        range=rng, kpis=kpis, timeline=timeline, cash_flow=cash, customers=health, alerts=alerts
    )


async def _alerts(
    session: AsyncSession, tl: Timeline, delayed: list[DelayedOrder], today: date
) -> list[Alert]:
    """Signposts to the source records (each alert links to where the issue lives)."""
    out: list[Alert] = []
    for m in tl.machines:
        if m.over and m.peak_day is not None:
            where = (
                f"/planning/{tl.draft.id}?step=3"
                if tl.draft
                else (f"/planning/{tl.plan.id}?step=3" if tl.plan else "/planning")
            )
            out.append(Alert(id=f"load-{m.machine}", source="planning", tone="hi", title=f"{m.name} over capacity",
                             text=f"{m.peak_after}% on {_short(m.peak_day)} after the new orders "
                                  f"(current plan {next((x.current for x in m.days if x.day == m.peak_day), 0)}%)",
                             at=m.peak_day, link=where))  # fmt: skip
    if tl.plan and tl.plan.needs_reapproval:
        out.append(Alert(id=f"reapprove-{tl.plan.id}", source="planning", tone="md",
                         title=f"{tl.plan.number} needs re-approval", text="The plan in force changed significantly",
                         at=None, link=f"/planning/{tl.plan.id}"))  # fmt: skip
    for o in delayed:
        out.append(Alert(id=f"order-{o.id}", source="orders", tone="hi", title=f"{o.number} · {o.customer}",
                         text=o.reason, at=o.due, link=f"/orders?q={o.number}"))  # fmt: skip
    for po in await purchasing.list_pos(session):
        link = f"/purchasing/purchase?po={po.id}"
        if po.stage == "delayed":
            out.append(Alert(id=f"po-{po.id}", source="purchasing", tone="hi", title=f"{po.number} delayed · {po.supplier}",
                             text=po.stage_text, at=po.expected_date, link=link))  # fmt: skip
        elif po.stage == "pending_approval":
            out.append(Alert(id=f"po-{po.id}", source="purchasing", tone="md", title=f"{po.number} awaiting your approval",
                             text=f"{po.supplier} · {po.stage_text}".rstrip(" ·"), at=po.created_at.date(), link=link))  # fmt: skip
        elif po.stage == "at_gate":
            out.append(Alert(id=f"po-{po.id}", source="purchasing", tone="bl", title=f"{po.number} at the gate",
                             text=po.stage_text or "Waiting for QC", at=po.expected_date, link=link))  # fmt: skip
    rec = await ar.receivables(session, None)
    for r in sorted((r for r in rec.rows if r.status == "overdue"), key=lambda r: -r.outstanding_paise)[:5]:
        out.append(Alert(id=f"ar-{r.customer_id}", source="billing", tone="hi" if r.days_overdue > 60 else "md",
                         title=f"{r.name} owes {ar.inr(r.outstanding_paise)}",
                         text=f"{r.days_overdue} days overdue" + (" · payment promised" if r.has_promise else ""),
                         at=r.earliest_due, link=f"/billing?customer={r.customer_id}"))  # fmt: skip
    pay = await ap.payables(session, None)
    for p in pay.rows:
        link = f"/billing?mode=ap&supplier={p.supplier_id}"
        if "pending_owner" in p.statuses:
            out.append(Alert(id=f"ap-own-{p.supplier_id}", source="billing", tone="md",
                             title=f"{p.name}: payment awaiting your approval",
                             text=f"{ar.inr(p.outstanding_paise)} outstanding", at=p.earliest_due, link=link))  # fmt: skip
        if p.overdue:
            out.append(Alert(id=f"ap-due-{p.supplier_id}", source="billing", tone="hi", title=f"{p.name} payment overdue",
                             text=f"{p.days_overdue} days past due", at=p.earliest_due, link=link))  # fmt: skip
    seen: dict[str, Alert] = {}
    for a in out:
        seen.setdefault(a.id, a)
    return sorted(seen.values(), key=lambda a: (TONE_ORDER[a.tone], SOURCE_ORDER[a.source], a.at or today))
