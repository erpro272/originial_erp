"""Planning: loads factory data + orders, runs the engine, keeps one working plan up to date.

"Everything is connected": the result is recalculated from the database every time a plan is read
or edited. A fingerprint of every input (orders, stock, factory data, rules, the owner's choices)
decides whether anything changed; if it did, a new version is saved, the history records it with
the tabs whose numbers moved, and an approved plan is marked "needs re-approval".
"""

import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.catalog.models import Material, MaterialStock, Product, ProductMaterial
from app.core import audit, clock, counters, events
from app.core.errors import DomainError, NotFound
from app.core.services import kv
from app.customers.models import Customer
from app.orders import service as orders_service
from app.orders.models import Order
from app.planning import engine as eng
from app.planning.models import (
    Department,
    Downtime,
    Machine,
    Plan,
    PlanEvent,
    PlanSnapshot,
    PurchaseRequest,
    RouteStep,
)
from app.planning.schemas import (
    ApproveIn,
    Diff,
    Factory,
    HistoryItem,
    LastChange,
    PlanningObjective,
    PlanningRules,
    PlanOut,
    PlanPatch,
    PlanResult,
    PlanSummary,
    PreviewOut,
    PurchaseRequestOut,
    SnapshotInfo,
)

RULES_KEY = "planning-rules"
OBJECTIVE_KEY = "planning-objective"
WORKING = ("draft", "generated")


# ---- rules ----------------------------------------------------------------------------------


async def get_rules(session: AsyncSession) -> PlanningRules:
    try:
        return PlanningRules.model_validate(await kv.get_setting(session, RULES_KEY))
    except (NotFound, ValueError):
        return PlanningRules()


async def put_rules(session: AsyncSession, actor: uuid.UUID, r: PlanningRules) -> PlanningRules:
    await kv.put_setting(session, actor, RULES_KEY, r.model_dump())
    return r


async def get_objective(session: AsyncSession) -> PlanningObjective:
    try:
        return PlanningObjective.model_validate(await kv.get_setting(session, OBJECTIVE_KEY))
    except (NotFound, ValueError):
        return PlanningObjective()


async def put_objective(session: AsyncSession, actor: uuid.UUID, o: PlanningObjective) -> PlanningObjective:
    await kv.put_setting(session, actor, OBJECTIVE_KEY, o.model_dump())
    return o


def _engine_rules(r: PlanningRules, o: PlanningObjective | None = None) -> eng.Rules:
    return eng.Rules(
        criteria=tuple((o or PlanningObjective()).criteria),
        penalty_mode=r.penalty_mode,
        penalty_value=r.penalty_fixed_paise if r.penalty_mode == "fixed" else r.penalty_percent,
        overhead_pct=r.overhead_pct,
        packaging_per_unit=r.packaging_paise_per_unit,
        min_margin_pct=r.min_margin_pct,
    )


# ---- loading inputs ---------------------------------------------------------------------------


async def load_factory(session: AsyncSession) -> eng.Factory:
    depts = {str(d.id): eng.Dept(str(d.id), d.name, float(d.hours_per_day), d.cost_per_hour_paise)
             for d in (await session.execute(select(Department))).scalars()}  # fmt: skip
    machines = {}
    for m in (
        await session.execute(select(Machine).where(Machine.active).order_by(Machine.sort, Machine.name))
    ).scalars():
        machines[str(m.id)] = eng.Machine(str(m.id), m.name, str(m.department_id),
                                        float(m.hours_per_shift) * m.shifts_per_day, float(m.hours_per_shift),
                                        m.cost_per_hour_paise, m.night_shift_cost_per_hour_paise, m.operators,
                                        m.inspection)  # fmt: skip
    stock = {s.material_id: s for s in (await session.execute(select(MaterialStock))).scalars()}
    materials = {}
    for mat in (await session.execute(select(Material))).scalars():
        st = stock.get(mat.id)
        materials[str(mat.id)] = eng.MaterialInfo(
            str(mat.id), mat.code, mat.name, mat.unit, float(st.on_hand) if st else 0.0,
            st.next_arrival_date if st else None, float(st.next_arrival_qty or 0) if st else 0.0,
            mat.price_per_unit_paise, mat.express_cost_paise, mat.express_days, mat.express_supplier or "",
        )  # fmt: skip
    closed: set[date] = set()
    down: dict[tuple[str, date], float] = {}
    for d in (await session.execute(select(Downtime))).scalars():
        if d.machine_id is None:
            closed.add(d.day)
        elif str(d.machine_id) in machines:
            mid = str(d.machine_id)
            down[(mid, d.day)] = float(d.hours) if d.hours is not None else machines[mid].hours_per_day
    return eng.Factory(machines, depts, materials, frozenset(closed), down)


async def _jobs(
    session: AsyncSession, plan: Plan | None
) -> tuple[list[eng.Job], list[eng.Job], dict[str, Order]]:
    """(candidates, running/booked, orders by id). Candidates = accepted orders + this plan's planned ones."""
    mine = set(plan.selected) if plan else set()
    routes: dict[uuid.UUID, list[RouteStep]] = {}
    for r in (await session.execute(select(RouteStep).order_by(RouteStep.seq))).scalars():
        routes.setdefault(r.product_id, []).append(r)
    boms: dict[uuid.UUID, list[ProductMaterial]] = {}
    for b in (await session.execute(select(ProductMaterial))).scalars():
        boms.setdefault(b.product_id, []).append(b)
    rows = (await session.execute(
        select(Order, Customer, Product).join(Customer, Customer.id == Order.customer_id)
        .join(Product, Product.id == Order.product_id)
        .where(Order.status.in_(("accepted", "planned", "in_production")))
        .order_by(Order.number)
    )).all()  # fmt: skip
    cands, running, by_id = [], [], {}
    for o, c, p in rows:
        qty = o.quantity
        approved_here = plan is not None and plan.status == "approved" and str(o.id) in mine
        job = eng.Job(
            id=str(o.id), number=o.number, customer=c.name, product=p.name, qty=float(qty), unit=o.unit,
            value=o.sales_paise, deadline=o.ship_date, priority=o.priority, tier=c.tier,
            steps=tuple(eng.Step(str(r.machine_id), float(r.setup_hours), float(qty * r.minutes_per_unit / Decimal(60)))
                        for r in routes.get(p.id, [])),
            materials=tuple((str(b.material_id), float(qty * b.qty_per_unit)) for b in boms.get(p.id, [])),
            running=o.status == "in_production" or (o.status == "planned" and str(o.id) not in mine),
            progress=o.progress_pct or 0,
        )  # fmt: skip
        by_id[job.id] = o
        approved_plan = plan is not None and plan.status == "approved"
        if approved_plan and o.status == "accepted" and str(o.id) not in mine:
            continue  # new orders belong to the next plan, not to an approved one
        if o.status == "accepted" or (o.status == "planned" and str(o.id) in mine) or approved_here:
            cands.append(job)
        else:
            running.append(job)
    return cands, running, by_id


async def _requested(session: AsyncSession, plan: Plan) -> dict[str, dict[str, Any]]:
    """Actual purchase requests for this plan (the latest per material): what Purchasing has been asked."""
    rows = (
        await session.execute(
            select(PurchaseRequest)
            .where(PurchaseRequest.plan_id == plan.id)
            .order_by(PurchaseRequest.created_at)
        )
    ).scalars()
    return {str(p.material_id): {"status": p.status, "at": p.created_at.date(), "express": p.express,
                                 "qty": float(p.quantity)} for p in rows}  # fmt: skip


def _fp(*parts: Any) -> str:
    return hashlib.sha256(
        json.dumps([eng.ENGINE_VERSION, *parts], default=str, sort_keys=True).encode()
    ).hexdigest()


def _inputs(plan: Plan) -> eng.Inputs:
    i = plan.inputs or {}
    return eng.Inputs(
        start=plan.start_date,
        sequence=list(i.get("sequence", [])),
        locks={k: date.fromisoformat(v) for k, v in i.get("locks", {}).items()},
        pins={k: date.fromisoformat(v) for k, v in i.get("pins", {}).items()},
        fixes=set(i.get("fixes", [])),
    )


def _store_inputs(plan: Plan, inp: eng.Inputs, extra: dict[str, Any] | None = None) -> None:
    plan.inputs = {
        **(plan.inputs or {}),
        "sequence": inp.sequence,
        "locks": {k: v.isoformat() for k, v in inp.locks.items()},
        "pins": {k: v.isoformat() for k, v in inp.pins.items()},
        "fixes": sorted(inp.fixes),
        **(extra or {}),
    }


async def _compute(session: AsyncSession, plan: Plan, today: date) -> tuple[dict[str, Any], str, str]:
    """(result, fingerprint, options fingerprint). Pure read: does not change the plan."""
    f = await load_factory(session)
    rules = await get_rules(session)
    objective = await get_objective(session)
    cands, running, _ = await _jobs(session, plan)
    requested = await _requested(session, plan)
    inp = _inputs(plan)
    base = list((plan.inputs or {}).get("base", plan.selected))
    own_order = [i for i in inp.sequence if i in base]
    ofp = _fp(
        f, rules.model_dump(), objective.model_dump(), cands, running, base, own_order, plan.start_date, today
    )
    opts = plan.result["selection"]["options"] if plan.result and plan.options_fingerprint == ofp else None
    result = eng.compute(f, _engine_rules(rules, objective), running, cands, list(plan.selected), plan.rule, inp,
                         today, requested, opts, base)  # fmt: skip
    # Fingerprint the inputs as the engine tidied them (sequence by rule etc.), so a re-read is stable.
    fp = _fp(f, rules.model_dump(), objective.model_dump(), cands, running, plan.selected, plan.rule,
             result["inputs"], plan.start_date, today, sorted(requested.items()))  # fmt: skip
    # What an approval is about: the plan's orders (qty, value, deadline, route, materials), factory data and
    # stock, company rules and the owner's choices. Not today's date and not production progress: an approved
    # plan doesn't need re-approval because a day passed or its orders moved into production.
    mine = sorted(((j.id, j.qty, j.value, j.deadline, j.steps, j.materials) for j in cands if j.id in plan.selected),
                  key=lambda x: x[0])  # fmt: skip
    if plan.status == "approved" and plan.selected:
        statuses = (await session.execute(
            select(Order.status).where(Order.id.in_([uuid.UUID(i) for i in plan.selected])))).scalars()  # fmt: skip
        # its orders are being made / shipped: Production carries it out now, no more re-approval checks
        result["_executing"] = any(st in ("in_production", "completed", "shipped") for st in statuses)
    result["_data_fp"] = _fp(f, rules.model_dump(), objective.model_dump(), mine, plan.rule,
                             {k: v for k, v in result["inputs"].items() if k != "sequence"}, plan.start_date)  # fmt: skip
    return result, fp, ofp


async def _save(session: AsyncSession, plan: Plan, result: dict[str, Any], fp: str, ofp: str,
                actor: uuid.UUID | None, kind: str, summary: str) -> list[int]:  # fmt: skip
    tabs = eng.changed_tabs(plan.result, result)
    plan.inputs = {**(plan.inputs or {}), **result["inputs"]}
    plan.result, plan.fingerprint, plan.options_fingerprint = result, fp, ofp
    plan.version += 1
    if plan.status == "approved":
        approved_fp = (plan.inputs or {}).get("approval_fp")
        if result.get("_executing"):
            pass  # in execution: keep the flag as it was
        elif approved_fp:  # the business data it was approved on has changed
            plan.needs_reapproval = result.get("_data_fp") != approved_fp
        elif set(tabs) & {2, 3, 4, 5}:  # plans approved before the fingerprint existed
            plan.needs_reapproval = True
    session.add(PlanEvent(plan_id=plan.id, kind=kind, summary=summary, tabs=tabs, actor_id=actor))
    await session.flush()
    return tabs


async def _refresh(session: AsyncSession, plan: Plan, today: date) -> Plan:
    """Bring the plan up to date with the rest of the ERP (orders, stock, factory data, rules)."""
    if plan.status in ("completed", "cancelled"):
        return plan  # finished plans are kept exactly as they ended
    if await _maybe_complete(session, plan):
        return plan
    synced = await _sync_with_orders(session, plan) if plan.status in WORKING else []
    if plan.status in WORKING and plan.start_date < today:  # a plan can't start in the past
        plan.start_date = eng.next_working(today, await load_factory(session))
    result, fp, ofp = await _compute(session, plan, today)
    if plan.status in WORKING and result["selection"]["using"] is None and result["selection"]["selected"]:
        # The ticked orders no longer match any option (data changed): they become the owner's own picks.
        plan.inputs = {**(plan.inputs or {}), "base": list(plan.selected)}
        result, fp, ofp = await _compute(session, plan, today)
    if fp != plan.fingerprint:
        old = set((plan.result or {}).get("selection", {}).get("orders", {}))
        new = set(result["selection"]["orders"])
        num = {**(plan.result or {}).get("selection", {}).get("orders", {}), **result["selection"]["orders"]}
        parts = list(synced)
        if new - old:
            parts.append("new in Orders: " + ", ".join(sorted(num[i]["number"] for i in new - old)))
        if old - new:
            parts.append("no longer plannable: " + ", ".join(sorted(num[i]["number"] for i in old - new)))
        summary = "Plan updated · " + ("; ".join(parts) if parts else "orders, stock or factory data changed")
        if plan.result is None:
            summary = "Plan started" + (f" · {'; '.join(synced)}" if synced else "")
        await _save(session, plan, result, fp, ofp, None, "refresh" if plan.result else "created", summary)
    return plan


async def _maybe_complete(session: AsyncSession, plan: Plan) -> bool:
    """An approved plan is completed once every one of its orders is shipped (or cancelled) in Orders.
    "completed" orders are made but not shipped yet, so they don't finish the plan."""
    if plan.status != "approved" or not plan.selected:
        return False
    statuses = list(
        (await session.execute(select(Order.status).where(Order.id.in_([uuid.UUID(i) for i in plan.selected])))).scalars()
    )  # fmt: skip
    if not statuses or not all(s in ("shipped", "cancelled") for s in statuses) or "shipped" not in statuses:
        return False
    plan.status, plan.completed_at, plan.needs_reapproval = "completed", datetime.now(UTC), False
    session.add(PlanEvent(plan_id=plan.id, kind="completed", tabs=[], created_at=datetime.now(UTC),
                          summary=f"Plan completed · all {len(statuses)} orders shipped or closed"))  # fmt: skip
    await audit.record(session, actor_id=None, action="update", entity_type="plan", entity_id=plan.id,
                       summary=f"{plan.number} completed")  # fmt: skip
    await session.flush()
    return True


async def _marked(session: AsyncSession) -> list[str]:
    """Accepted orders that are 'In planning' in Orders received."""
    q = select(Order.id).where(Order.status == "accepted", Order.marked_for_planning).order_by(Order.number)
    return [str(i) for i in (await session.execute(q)).scalars()]


async def _sync_with_orders(session: AsyncSession, plan: Plan) -> list[str]:
    """Ticked in Planning == "In planning" in Orders: one fact, kept the same both ways.

    Planning edits write the flag through the Orders service (see update_plan); here, changes made in
    Orders (Send to / Remove from Planning, cancel, status change) flow into the working plan.
    """
    marked = await _marked(session)
    keep = [i for i in plan.selected if i in marked]
    new = keep + [i for i in marked if i not in keep]
    if new == list(plan.selected):
        return []
    added, removed = set(new) - set(plan.selected), set(plan.selected) - set(new)
    nums = {
        str(o.id): o.number
        for o in (await session.execute(select(Order).where(Order.id.in_([uuid.UUID(i) for i in added | removed])))).scalars()
    }  # fmt: skip
    plan.selected = new
    plan.inputs = {**(plan.inputs or {}), "base": new}  # the owner's own picks changed in Orders
    out = []
    if added:
        out.append("sent from Orders received: " + ", ".join(sorted(nums.get(i, "?") for i in added)))
    if removed:
        out.append("no longer in planning: " + ", ".join(sorted(nums.get(i, "?") for i in removed)))
    return out


# ---- output ---------------------------------------------------------------------------------


async def _snapshots(session: AsyncSession, plan_id: uuid.UUID) -> list[PlanSnapshot]:
    q = select(PlanSnapshot).where(PlanSnapshot.plan_id == plan_id).order_by(PlanSnapshot.version.desc())
    return list((await session.execute(q)).scalars())


async def _out(session: AsyncSession, plan: Plan, snapshot: PlanSnapshot | None = None) -> PlanOut:
    """The plan as the screens read it. With `snapshot`: exactly what was approved (frozen)."""
    ev = (await session.execute(select(PlanEvent).where(PlanEvent.plan_id == plan.id)
                                .order_by(PlanEvent.created_at.desc(), PlanEvent.id).limit(1))).scalar_one_or_none()  # fmt: skip
    assert plan.result is not None
    snaps = await _snapshots(session, plan.id)
    result = snapshot.result if snapshot else plan.result
    hint = result["sequence"]["hint"]
    if hint and (plan.inputs or {}).get("dismissed_hint") == hint["sequence"]:
        result = {**result, "sequence": {**result["sequence"], "hint": {**hint, "dismissed": True}}}
    return PlanOut(
        id=plan.id, number=plan.number, status=plan.status, needs_reapproval=plan.needs_reapproval, rule=plan.rule,
        start_date=plan.start_date, version=plan.version, generated_at=plan.generated_at,
        approved_at=plan.approved_at, approval_note=plan.approval_note,
        result=PlanResult.model_validate(result),
        last_change=LastChange(summary=ev.summary, tabs=ev.tabs, at=ev.created_at) if ev else None,
        schedule_saved_at=(plan.inputs or {}).get("schedule_saved_at"),
        changes_requested=(plan.inputs or {}).get("changes_requested"),
        view="snapshot" if snapshot else "live",
        snapshot=SnapshotInfo(version=snapshot.version, approved_at=snapshot.approved_at, note=snapshot.note) if snapshot else None,
        snapshots=[SnapshotInfo(version=s.version, approved_at=s.approved_at, note=s.note) for s in snaps],
        completed_at=plan.completed_at, cancelled_at=plan.cancelled_at, cancel_reason=plan.cancel_reason,
    )  # fmt: skip


# ---- public API ------------------------------------------------------------------------------


async def current_plan(session: AsyncSession) -> Plan | None:
    """The working plan, or else the latest approved one (cancelled and completed plans are history)."""
    q = (select(Plan).where(Plan.status.in_((*WORKING, "approved")), Plan.deleted_at.is_(None))
         .order_by(Plan.status.in_(WORKING).desc(), Plan.created_at.desc()).limit(1))  # fmt: skip
    return (await session.execute(q)).scalar_one_or_none()


async def get_current(session: AsyncSession) -> PlanOut | None:
    plan = await current_plan(session)
    idle = plan is None or (plan.status == "approved" and not plan.needs_reapproval)
    if idle and await _marked(session):
        # Orders were sent to Planning and nothing is being planned: start the next plan for them.
        return await _new_plan(session, None)
    if plan is None:
        return None
    return await _out(session, await _refresh(session, plan, clock.today()))


async def _get(session: AsyncSession, plan_id: uuid.UUID) -> Plan:
    plan = await session.get(Plan, plan_id, with_for_update=True)
    if plan is None or plan.deleted_at is not None:
        raise NotFound("Plan not found.")
    return plan


async def create_plan(session: AsyncSession, actor: uuid.UUID) -> PlanOut:
    cur = await current_plan(session)
    if cur is not None and cur.status in WORKING:
        raise DomainError(f"{cur.number} is still being worked on. Approve it first, or keep editing it.")
    return await _new_plan(session, actor)


async def _new_plan(session: AsyncSession, actor: uuid.UUID | None) -> PlanOut:
    n = await counters.next_value(session, "plan", start=0)
    marked = await _marked(session)
    start = eng.next_working(clock.today(), await load_factory(session))
    plan = Plan(number=f"PLAN-{n:03d}", status="draft", rule="value",  # mockup default: highest value first
                start_date=start, selected=marked,
                inputs={"base": marked})  # fmt: skip
    session.add(plan)
    await session.flush()
    await audit.record(session, actor_id=actor, action="create", entity_type="plan", entity_id=plan.id,
                       summary=f"{plan.number} started")  # fmt: skip
    await _refresh(session, plan, clock.today())
    return await _out(session, plan)


def _check_locks(old: list[str], new: list[str], locks: dict[str, date]) -> None:
    for jid in locks:
        if jid in old and jid in new and old.index(jid) != new.index(jid):
            raise DomainError("Locked orders keep their slot. Unlock it first to move it.")


def _apply(plan: Plan, p: PlanPatch, result: dict[str, Any]) -> tuple[list[str], str]:
    """Apply one edit to the plan's inputs (in memory). Returns (selected, summary)."""
    inp = _inputs(plan)
    num = {k: v["number"] for k, v in result["selection"]["orders"].items()}
    selected = list(plan.selected)
    base = list((plan.inputs or {}).get("base", selected))
    summary = "Plan changed"
    if p.use_option:
        opt = result["selection"]["options"].get(p.use_option)
        if not opt:
            raise DomainError("That option isn't available.")
        selected = list(opt["orders"])  # the owner's own picks (base) stay, so the 3 options stay comparable
        # Step 2 runs the option exactly as it was scored on step 1 (its own best order).
        inp.sequence = [i for i in opt.get("sequence", opt["orders"]) if i in selected]
        inp.locks = {k: v for k, v in inp.locks.items() if k in selected}
        if p.use_option != "own":
            plan.rule = "custom"
        label = {
            "own": "your selection",
            "part": "the partly optimized selection",
            "full": "the fully optimized selection",
        }
        summary = f"Using {label[p.use_option]}"
    if p.selected is not None:
        unknown = [i for i in p.selected if i not in num]
        if unknown:
            raise DomainError("Some orders can't be planned (not accepted).")
        added = [i for i in p.selected if i not in selected]
        removed = [i for i in selected if i not in p.selected]
        selected = list(p.selected)
        base = list(selected)  # ticking by hand = the owner's own picks
        bits = ([f"added {', '.join(num[i] for i in added)}"] if added else []) + (
            [f"removed {', '.join(num[i] for i in removed)}"] if removed else [])  # fmt: skip
        summary = "Orders selected · " + "; ".join(bits) if bits else "Orders selected"
    if p.rule:
        plan.rule = p.rule
        summary = f"Sequenced by {p.rule}"
    if p.start_date:
        if p.start_date < clock.today():
            raise DomainError("The plan can't start in the past.")
        plan.start_date = p.start_date
        inp.start = p.start_date
        summary = f"Start date set to {p.start_date.isoformat()}"
    if p.apply_hint:
        hint = result["sequence"]["hint"]
        if not hint:
            raise DomainError("There is no suggestion to apply.")
        p = p.model_copy(update={"sequence": hint["sequence"]})
        summary = f"Sequence changed · {hint['title']}"
    if p.dismiss_hint:
        hint = result["sequence"]["hint"]
        if hint:
            _store_inputs(plan, inp, {"dismissed_hint": hint["sequence"]})
            summary = f"Suggestion dismissed · {hint['title']}"
    if p.sequence is not None:
        if sorted(p.sequence) != sorted(inp.sequence):
            raise DomainError("The new order must contain the same orders.")
        _check_locks(inp.sequence, p.sequence, inp.locks)
        moved = next((x for x, y in zip(p.sequence, inp.sequence, strict=True) if x != y), None)
        inp.sequence = list(p.sequence)
        plan.rule = "custom"
        if not p.apply_hint:
            summary = f"Sequence changed · {num.get(moved, '')} moved" if moved else "Sequence unchanged"
    if p.lock:
        rows = {r["id"]: r for r in result["sequence"]["rows"]}
        for jid, on in p.lock.items():
            if on and jid in rows:
                inp.locks[jid] = date.fromisoformat(rows[jid]["start"])
            else:
                inp.locks.pop(jid, None)
            summary = f"{num.get(jid, '')} {'locked' if on else 'unlocked'}"
    if p.pin:
        for jid, d in p.pin.items():
            if d is None:
                inp.pins.pop(jid, None)
            else:
                if d < inp.start:
                    raise DomainError("A finish date can't be before the plan starts.")
                inp.pins[jid] = d
            summary = f"{num.get(jid, '')} finish date " + (f"set to {d.isoformat()}" if d else "released")
    if p.fixes is not None:
        fx_added = set(p.fixes) - inp.fixes
        fx_removed = inp.fixes - set(p.fixes)
        inp.fixes = set(p.fixes)
        labels = {f["id"]: f["label"] for f in result["finance"]["fixes"]}
        bits = [f"applied {labels.get(x, x)}" for x in sorted(fx_added)] + [
            f"removed {labels.get(x, x)}" for x in sorted(fx_removed)
        ]
        summary = "Fixes · " + "; ".join(bits) if bits else "Fixes unchanged"
    _store_inputs(plan, inp, {"base": base})
    return selected, summary


async def update_plan(session: AsyncSession, actor: uuid.UUID, plan_id: uuid.UUID, p: PlanPatch,
                      preview: bool) -> PreviewOut:  # fmt: skip
    plan = await _get(session, plan_id)
    if plan.status not in WORKING:
        raise DomainError(f"This plan is {plan.status} and read-only. Start a new plan to make changes.")
    today = clock.today()
    await _refresh(session, plan, today)
    assert plan.result is not None
    before = plan.result
    snapshot = (list(plan.selected), dict(plan.inputs or {}), plan.rule, plan.start_date)
    plan.selected, summary = _apply(plan, p, before)
    result, fp, ofp = await _compute(session, plan, today)
    new_blocks = {k: v for k, v in result["blocked"].items() if k not in before.get("blocked", {})}
    diff = eng.bottleneck_diff(before, result)
    blocked = next(iter(new_blocks.values()), None)
    tabs = eng.changed_tabs(before, result)
    if preview or blocked:
        plan.selected, plan.inputs, plan.rule, plan.start_date = snapshot  # nothing is saved
        if blocked and not preview:
            raise DomainError(blocked)
        out = await _out(session, plan)
        out = out.model_copy(update={"result": PlanResult.model_validate(result)})
        return PreviewOut(plan=out, diff=Diff.model_validate(diff | {"blocked": blocked}), tabs=tabs)
    if plan.status == "approved":
        summary += " · needs re-approval"
    if plan.status in WORKING:
        await _write_ticks_to_orders(session, actor, snapshot[0], list(plan.selected))
    plan.inputs = {k: v for k, v in (plan.inputs or {}).items() if k != "changes_requested"}
    tabs = await _save(session, plan, result, fp, ofp, actor, "change", summary)
    await audit.record(session, actor_id=actor, action="update", entity_type="plan", entity_id=plan.id,
                       summary=f"{plan.number}: {summary}")  # fmt: skip
    return PreviewOut(plan=await _out(session, plan), diff=Diff.model_validate(diff), tabs=tabs)


async def _write_ticks_to_orders(
    session: AsyncSession, actor: uuid.UUID, old: list[str], new: list[str]
) -> None:
    """Planning ticks -> "In planning" on the orders, through the Orders service."""
    added = [uuid.UUID(i) for i in new if i not in old]
    removed = [uuid.UUID(i) for i in old if i not in new]
    if added:
        await orders_service.set_planning_selection(session, actor, added, True)
    if removed:
        await orders_service.set_planning_selection(session, actor, removed, False)


async def generate(session: AsyncSession, actor: uuid.UUID, plan_id: uuid.UUID) -> PlanOut:
    plan = await _get(session, plan_id)
    if plan.status not in WORKING:
        raise DomainError(f"This plan is {plan.status} and read-only. Start a new plan to make changes.")
    await _refresh(session, plan, clock.today())
    assert plan.result is not None
    n = len(plan.result["sequence"]["rows"])
    if n == 0:
        raise DomainError("Tick at least one order to plan.")
    if plan.status == "draft":
        plan.status = "generated"
    plan.generated_at = datetime.now(UTC)
    session.add(PlanEvent(plan_id=plan.id, kind="generated", summary=f"Plan generated · {n} order{'s' * (n != 1)}",
                          tabs=[2, 3, 4, 5], actor_id=actor))  # fmt: skip
    await audit.record(session, actor_id=actor, action="update", entity_type="plan", entity_id=plan.id,
                       summary=f"{plan.number} generated")  # fmt: skip
    await session.flush()
    return await _out(session, plan)


async def save_schedule(session: AsyncSession, actor: uuid.UUID, plan_id: uuid.UUID) -> PlanOut:
    """Step 3 "Save schedule": a checkpoint in the plan history (every edit is already live)."""
    plan = await _get(session, plan_id)
    if plan.status not in WORKING:
        raise DomainError(f"This plan is {plan.status} and read-only. Start a new plan to make changes.")
    await _refresh(session, plan, clock.today())
    if not plan.generated_at:
        raise DomainError("Generate the plan first.")
    plan.inputs = {**(plan.inputs or {}), "schedule_saved_at": datetime.now(UTC).isoformat()}
    session.add(PlanEvent(plan_id=plan.id, kind="saved", summary="Schedule saved", tabs=[], actor_id=actor))
    await audit.record(session, actor_id=actor, action="update", entity_type="plan", entity_id=plan.id,
                       summary=f"{plan.number}: schedule saved")  # fmt: skip
    await session.flush()
    return await _out(session, plan)


async def _request_po(
    session: AsyncSession, plan: Plan, actor: uuid.UUID, need: dict[str, Any], source: str
) -> None:
    session.add(PurchaseRequest(plan_id=plan.id, material_id=uuid.UUID(need["material"]), quantity=Decimal(str(need["qty"])),
                                unit=need["unit"], needed_by=date.fromisoformat(need["needed_by"]),
                                express=need.get("action") in ("express_po", "expedite"), order_numbers=need["orders"], source=source,
                                requested_by=actor))  # fmt: skip
    session.add(PlanEvent(plan_id=plan.id, kind="po", tabs=[5], actor_id=actor,
                          summary=f"PO requested · {need['qty']:g} {need['unit']} {need['name']} by {eng._fmt_day(date.fromisoformat(need['needed_by']))}"))  # fmt: skip
    await session.flush()


async def raise_po(session: AsyncSession, actor: uuid.UUID, plan_id: uuid.UUID, material_id: str) -> PlanOut:
    plan = await _get(session, plan_id)
    await _refresh(session, plan, clock.today())
    assert plan.result is not None
    need = next((n for n in plan.result["purchase_needs"] if n["material"] == material_id), None)
    if need is None:
        raise DomainError("This plan doesn't need that material.")
    if need["requested"]:
        raise DomainError("A PO for this material was already requested.")
    if not need.get("action"):
        raise DomainError(f"{need['name']} is already on order; there is nothing to raise.")
    await _request_po(session, plan, actor, need, "raise_now")
    await _refresh(session, plan, clock.today())
    return await _out(session, plan)


async def approve(session: AsyncSession, actor: uuid.UUID, plan_id: uuid.UUID, body: ApproveIn) -> PlanOut:
    plan = await _get(session, plan_id)
    await _refresh(session, plan, clock.today())
    r = plan.result
    assert r is not None
    if plan.status == "draft":
        raise DomainError("Generate the plan before approving it.")
    if plan.status == "approved" and not plan.needs_reapproval:
        raise DomainError("This plan is already approved.")
    open_needs = [n for n in r["purchase_needs"] if n.get("action") and not n["requested"]]
    # the owner may approve with open items (after the warning); they are kept in the history
    open_items = [
        c["title"] for c in r["approval"]["checks"] if not c["ok"] and c.get("action") != "raise_po"
    ]
    if open_needs and not body.raise_open_pos:
        raise DomainError(
            "Some material POs are not raised yet.", details={"open": [n["name"] for n in open_needs]}
        )
    for n in open_needs:
        await _request_po(session, plan, actor, n, "approval")
    promised = {uuid.UUID(row["id"]): date.fromisoformat(row["finish"]) for row in r["sequence"]["rows"]}
    await orders_service.set_planned(session, actor, promised)
    plan.status = "approved"
    plan.approved_at = datetime.now(UTC)
    plan.approved_by = actor
    plan.approval_note = body.note
    plan.inputs = {k: v for k, v in (plan.inputs or {}).items() if k != "changes_requested"}
    # recalculate as approved (other accepted orders are no longer candidates): not a "change" event
    result, fp, ofp = await _compute(session, plan, clock.today())
    plan.result, plan.fingerprint, plan.options_fingerprint = result, fp, ofp
    plan.version += 1
    plan.needs_reapproval = False
    plan.inputs = {**(plan.inputs or {}), "approval_fp": result.get("_data_fp")}
    # a frozen copy of exactly what was approved: never updated or deleted (re-approval adds v2, v3...)
    n = len(await _snapshots(session, plan.id))
    session.add(PlanSnapshot(plan_id=plan.id, version=n + 1, result=result, inputs=dict(plan.inputs or {}),
                             rule=plan.rule, approved_at=plan.approved_at, approved_by=actor, note=body.note))  # fmt: skip  # the approval itself (POs, planned orders) is the new baseline
    extra = ([f"{len(open_needs)} PO{'s' * (len(open_needs) != 1)} sent to Purchasing"] if open_needs else []) + (
        [f"approved with open items: {'; '.join(open_items)}"] if open_items else [])  # fmt: skip
    # exact time (not the transaction's start) so it lists after the PO requests it just made
    session.add(PlanEvent(plan_id=plan.id, kind="approved", tabs=[], actor_id=actor, created_at=datetime.now(UTC),
                          summary="Plan approved" + "".join(f" · {x}" for x in [body.note, *extra] if x)))  # fmt: skip
    await events.emit(session, "plan.approved", {
        "plan_id": str(plan.id), "number": plan.number,
        "schedule": [{"order_id": row["id"], "steps": row["steps"]} for row in r["schedule"]["rows"] if not row["running"]],
    })  # fmt: skip
    await audit.record(session, actor_id=actor, action="update", entity_type="plan", entity_id=plan.id,
                       summary=f"{plan.number} approved")  # fmt: skip
    await session.flush()
    return await _out(session, plan)


def _stage(plan: Plan) -> str:
    if plan.status == "approved":
        return "needs_reapproval" if plan.needs_reapproval else "approved"
    if plan.status == "generated":
        return "awaiting"
    return plan.status  # draft | completed | cancelled


async def list_plans(session: AsyncSession) -> list[PlanSummary]:
    """Every plan, newest first. Approved / completed plans show the money of their latest approved version."""
    q = (select(Plan).where(Plan.status == "approved", Plan.deleted_at.is_(None))
         .order_by(Plan.created_at.desc()).limit(1))  # fmt: skip
    cur = (await session.execute(q)).scalar_one_or_none()
    if cur is not None:
        # the latest approved plan is the one still in force: check whether data has changed since approval
        await _refresh(session, cur, clock.today())
    plans = list((await session.execute(
        select(Plan).where(Plan.deleted_at.is_(None)).order_by(Plan.created_at.desc()))).scalars())  # fmt: skip
    out = []
    for p in plans:
        await _maybe_complete(session, p)
        snaps = await _snapshots(session, p.id) if p.status in ("approved", "completed") else []
        r = snaps[0].result if snaps else (p.result or {})
        fin = (r.get("finance") or {}).get("with") or {}
        ov = (r.get("sequence") or {}).get("overview") or {}
        out.append(PlanSummary(
            id=p.id, number=p.number, status=p.status, stage=_stage(p), created_at=p.created_at,
            orders=len((r.get("selection") or {}).get("selected") or p.selected or []),
            start=ov.get("start"), end=ov.get("end"), approved_at=p.approved_at, completed_at=p.completed_at,
            cancelled_at=p.cancelled_at, value=fin.get("value", 0), contribution=fin.get("contribution", 0),
            margin=fin.get("margin", 0.0), snapshot_version=snaps[0].version if snaps else None,
        ))  # fmt: skip
    return out


async def get_plan(session: AsyncSession, plan_id: uuid.UUID, view: str | None) -> PlanOut:
    """One plan. Approved / completed plans open on their frozen approved version unless view == "live"
    (the recalculation that shows what changed since approval)."""
    plan = await session.get(Plan, plan_id)
    if plan is None or plan.deleted_at is not None:
        raise NotFound("Plan not found.")
    if plan.status in ("approved", "completed") and view != "live":
        await _maybe_complete(session, plan)
        snaps = await _snapshots(session, plan.id)
        if snaps:
            return await _out(session, plan, snaps[0])
    await _refresh(session, plan, clock.today())
    return await _out(session, plan)


async def cancel(session: AsyncSession, actor: uuid.UUID, plan_id: uuid.UUID, reason: str) -> PlanOut:
    """Owner: cancel a draft or awaiting plan. Its orders go back to accepted, not in planning."""
    plan = await _get(session, plan_id)
    if plan.status not in WORKING:
        raise DomainError("Only a draft or a plan awaiting approval can be cancelled.")
    await _write_ticks_to_orders(session, actor, list(plan.selected), [])
    plan.status, plan.cancelled_at, plan.cancel_reason = "cancelled", datetime.now(UTC), reason
    session.add(PlanEvent(plan_id=plan.id, kind="cancelled", tabs=[], actor_id=actor, created_at=datetime.now(UTC),
                          summary=f"Plan cancelled · {reason}"))  # fmt: skip
    await audit.record(session, actor_id=actor, action="update", entity_type="plan", entity_id=plan.id,
                       summary=f"{plan.number} cancelled: {reason}")  # fmt: skip
    await session.flush()
    return await _out(session, plan)


DELETABLE = ("draft", "generated", "cancelled")


async def delete_plan(session: AsyncSession, actor: uuid.UUID, plan_id: uuid.UUID) -> None:
    """Owner: remove a plan that was never approved (draft, awaiting, cancelled) from every screen.
    Approved and completed plans (and their snapshots) are never deleted. The row stays, hidden, with who
    and when, plus an audit entry; a deleted draft's orders go back to accepted, not in planning."""
    plan = await _get(session, plan_id)
    if plan.status not in DELETABLE:
        raise DomainError("Approved and completed plans are kept for good and can't be deleted.")
    if plan.status in WORKING:
        await _write_ticks_to_orders(session, actor, list(plan.selected), [])
    plan.deleted_at, plan.deleted_by = datetime.now(UTC), actor
    session.add(PlanEvent(plan_id=plan.id, kind="deleted", tabs=[], actor_id=actor, created_at=datetime.now(UTC),
                          summary=f"Plan deleted ({plan.status})"))  # fmt: skip
    await audit.record(session, actor_id=actor, action="delete", entity_type="plan", entity_id=plan.id,
                       summary=f"{plan.number} deleted (was {plan.status})")  # fmt: skip
    await session.flush()


async def send_back(session: AsyncSession, actor: uuid.UUID, plan_id: uuid.UUID, note: str | None) -> PlanOut:
    """Owner: "Send back to edit". Recorded with the note; the plan shows "Changes requested"."""
    plan = await _get(session, plan_id)
    if plan.status == "approved":
        raise DomainError("This plan is already approved. Start a new plan to make changes.")
    await _refresh(session, plan, clock.today())
    plan.inputs = {
        **(plan.inputs or {}),
        "changes_requested": {"note": note or "", "at": datetime.now(UTC).isoformat()},
    }
    session.add(PlanEvent(plan_id=plan.id, kind="sent_back", tabs=[], actor_id=actor,
                          summary="Sent back to edit" + (f" · {note}" if note else "")))  # fmt: skip
    await audit.record(session, actor_id=actor, action="update", entity_type="plan", entity_id=plan.id,
                       summary=f"{plan.number} sent back to edit")  # fmt: skip
    await session.flush()
    return await _out(session, plan)


async def history(session: AsyncSession, plan_id: uuid.UUID) -> list[HistoryItem]:
    rows = (await session.execute(select(PlanEvent).where(PlanEvent.plan_id == plan_id)
                                  .order_by(PlanEvent.created_at.desc()).limit(100))).scalars()  # fmt: skip
    return [HistoryItem(kind=e.kind, summary=e.summary, tabs=e.tabs, at=e.created_at) for e in rows]


async def purchase_requests(session: AsyncSession) -> list[PurchaseRequestOut]:
    rows = (await session.execute(select(PurchaseRequest, Material).join(Material, Material.id == PurchaseRequest.material_id)
                                  .order_by(PurchaseRequest.created_at.desc()))).all()  # fmt: skip
    return [PurchaseRequestOut(id=p.id, material=m.name, quantity=p.quantity, unit=p.unit, needed_by=p.needed_by,
                               express=p.express, order_numbers=p.order_numbers, source=p.source, status=p.status,
                               created_at=p.created_at) for p, m in rows]  # fmt: skip


# ---- factory setup ----------------------------------------------------------------------------


async def get_factory(session: AsyncSession) -> Factory:
    depts = list((await session.execute(select(Department).order_by(Department.name))).scalars())
    dname = {d.id: d.name for d in depts}
    machines = list(
        (
            await session.execute(select(Machine).where(Machine.active).order_by(Machine.sort, Machine.name))
        ).scalars()
    )
    mname = {m.id: m.name for m in machines}
    products = list((await session.execute(select(Product).order_by(Product.name))).scalars())
    steps: dict[uuid.UUID, list[RouteStep]] = {}
    for r in (await session.execute(select(RouteStep).order_by(RouteStep.seq))).scalars():
        steps.setdefault(r.product_id, []).append(r)
    mats = list((await session.execute(select(Material).order_by(Material.code))).scalars())
    down = list((await session.execute(select(Downtime).order_by(Downtime.day))).scalars())
    return Factory.model_validate({
        "departments": [{"id": d.id, "name": d.name, "hours_per_day": d.hours_per_day,
                         "cost_per_hour_paise": d.cost_per_hour_paise} for d in depts],
        "machines": [{"id": m.id, "name": m.name, "department": dname[m.department_id],
                      "hours_per_shift": m.hours_per_shift, "shifts_per_day": m.shifts_per_day,
                      "operators": m.operators, "cost_per_hour_paise": m.cost_per_hour_paise,
                      "night_shift_cost_per_hour_paise": m.night_shift_cost_per_hour_paise,
                      "inspection": m.inspection} for m in machines],
        "routes": [{"product_id": p.id, "product": p.name,
                    "steps": [{"machine": mname.get(s.machine_id, "?"), "setup_hours": s.setup_hours,
                               "minutes_per_unit": s.minutes_per_unit} for s in steps.get(p.id, [])]}
                   for p in products],
        "materials": [{"id": m.id, "code": m.code, "name": m.name, "unit": m.unit,
                       "price_per_unit_paise": m.price_per_unit_paise, "express_cost_paise": m.express_cost_paise,
                       "express_days": m.express_days, "express_supplier": m.express_supplier} for m in mats],
        "downtime": [{"machine": mname.get(d.machine_id) if d.machine_id else None, "day": d.day,
                      "hours": d.hours, "reason": d.reason} for d in down],
    })  # fmt: skip


async def put_factory(session: AsyncSession, actor: uuid.UUID, body: Factory) -> Factory:
    """Replace the factory set-up (upsert by id; machines/departments left out are removed if unused)."""
    for kind, names in (
        ("department", [d.name for d in body.departments]),
        ("machine", [m.name for m in body.machines]),
    ):
        dup = {n for n in names if names.count(n) > 1}
        if dup:
            raise DomainError(f"Two {kind}s are called {sorted(dup)[0]}.")
    depts = {dep.id: dep for dep in (await session.execute(select(Department))).scalars()}
    keep: dict[str, Department] = {}
    for di in body.departments:
        dep = depts.get(di.id) if di.id else None
        if dep is None:
            dep = Department(
                name=di.name, hours_per_day=di.hours_per_day, cost_per_hour_paise=di.cost_per_hour_paise
            )
            session.add(dep)
        else:
            dep.name, dep.hours_per_day, dep.cost_per_hour_paise = (
                di.name,
                di.hours_per_day,
                di.cost_per_hour_paise,
            )
        keep[di.name] = dep
    await session.flush()
    machines = {mac.id: mac for mac in (await session.execute(select(Machine))).scalars()}
    mkeep: dict[str, Machine] = {}
    for i, mi in enumerate(body.machines):
        if mi.department not in keep:
            raise DomainError(f"{mi.name}: department '{mi.department}' doesn't exist.")
        mac = machines.get(mi.id) if mi.id else None
        if mac is None:
            mac = Machine(
                name=mi.name, department_id=keep[mi.department].id, hours_per_shift=mi.hours_per_shift
            )
            session.add(mac)
        mac.name, mac.department_id, mac.hours_per_shift = mi.name, keep[mi.department].id, mi.hours_per_shift
        mac.shifts_per_day, mac.operators, mac.sort, mac.active = mi.shifts_per_day, mi.operators, i, True
        mac.cost_per_hour_paise = mi.cost_per_hour_paise
        mac.night_shift_cost_per_hour_paise = mi.night_shift_cost_per_hour_paise
        mac.inspection = mi.inspection
        mkeep[mi.name] = mac
    await session.flush()
    for r in body.routes:
        for st in r.steps:
            if st.machine not in mkeep:
                raise DomainError(f"{r.product or 'A product'}: machine '{st.machine}' doesn't exist.")
        for old in (
            await session.execute(select(RouteStep).where(RouteStep.product_id == r.product_id))
        ).scalars():
            await session.delete(old)
        await session.flush()
        for seq, st in enumerate(r.steps, start=1):
            session.add(RouteStep(product_id=r.product_id, seq=seq, machine_id=mkeep[st.machine].id,
                                  setup_hours=st.setup_hours, minutes_per_unit=st.minutes_per_unit))  # fmt: skip
    await session.flush()
    used = set((await session.execute(select(RouteStep.machine_id))).scalars())
    kept_ids = {mac.id for mac in mkeep.values()}
    for mid, mac in machines.items():
        if mid not in kept_ids:
            if mid in used:
                raise DomainError(f"{mac.name} is still used in a product route.")
            mac.active = False
    kept_depts = {dep.id for dep in keep.values()}
    in_use = {mac.department_id for mac in mkeep.values()}
    for did, dep in depts.items():
        if did not in kept_depts:
            if did in in_use:
                raise DomainError(f"{dep.name} still has machines.")
            await session.delete(dep)
    mats = {mat.id: mat for mat in (await session.execute(select(Material))).scalars()}
    for mc in body.materials:
        mat = mats.get(mc.id)
        if mat is None:
            raise NotFound("Material not found.")
        mat.price_per_unit_paise, mat.express_cost_paise = mc.price_per_unit_paise, mc.express_cost_paise
        mat.express_days, mat.express_supplier = mc.express_days, mc.express_supplier
    for dt in (await session.execute(select(Downtime))).scalars():
        await session.delete(dt)
    for dti in body.downtime:
        if dti.machine is not None and dti.machine not in mkeep:
            raise DomainError(f"Downtime: machine '{dti.machine}' doesn't exist.")
        session.add(Downtime(machine_id=mkeep[dti.machine].id if dti.machine else None, day=dti.day,
                             hours=dti.hours, reason=dti.reason))  # fmt: skip
    await session.flush()
    await audit.record(session, actor_id=actor, action="update", entity_type="factory", entity_id=None,
                       summary="Factory set-up changed")  # fmt: skip
    return await get_factory(session)
