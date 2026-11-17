"""Write actions the assistant proposes (handover C). The assistant never changes anything itself:

1. a tool returns a recommended action with a typed payload;
2. the chat turn stores it as an `ai_action_proposals` row (owner = the user, payload hash, 24 h expiry, idempotency
   key) and streams it to the screen;
3. the user ticks it and clicks Apply: `preview` re-checks it against live data and shows what will happen;
4. `approve` (same user, the action's permission, payload hash = what was reviewed, row locked) re-validates again and
   executes it through the owning module's service, which writes its own audit; the proposal records the result.
Executing twice is impossible: an executed proposal returns its stored result.
"""

import hashlib
import json
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.assistant.models import AiActionProposal
from app.ai.assistant.schemas import ProposalApproveItem, ProposalOut, ProposalPreview
from app.billing import receivables as ar
from app.billing.schemas import ArFollowUpIn
from app.core import audit, clock
from app.core.auth import Principal
from app.core.errors import DomainError, Forbidden, NotFound
from app.core.permissions import Permission
from app.planning import service as planning
from app.planning.schemas import PlanPatch
from app.purchasing import service as purchasing
from app.purchasing.schemas import PoRaiseIn

TTL = timedelta(hours=24)
PERMISSION: dict[str, Permission] = {
    "plan_fix": Permission.PLANNING_WRITE,
    "plan_sequence": Permission.PLANNING_WRITE,
    "raise_po": Permission.PURCHASING_WRITE,
    "follow_up": Permission.BILLING_WRITE,
}
NEEDS = {"plan_fix": "Planning edit access", "plan_sequence": "Planning edit access",
         "raise_po": "Purchasing edit access", "follow_up": "Billing edit access"}  # fmt: skip
RULES = {"deadline": "Earliest ship date first", "value": "Highest value first", "margin": "Highest margin first",
         "priority": "Priority first"}  # fmt: skip


def payload_hash(action_type: str, payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps([action_type, payload], sort_keys=True, default=str).encode()
    ).hexdigest()


def _out(p: Principal, r: AiActionProposal, now: datetime | None = None) -> ProposalOut:
    status = r.status
    if status == "pending" and r.expires_at <= (now or datetime.now(UTC)):
        status = "expired"
    perm = PERMISSION.get(r.action_type)
    return ProposalOut(id=r.id, kind=r.action_type, label=r.label, detail=r.detail, status=status,
                       allowed=bool(perm and p.can(perm)), needs=NEEDS.get(r.action_type, ""),
                       payload_hash=r.payload_hash, editable=["note"] if r.action_type == "follow_up" else [],
                       note=r.payload.get("note") if r.action_type == "follow_up" else None,
                       result=r.result, expires_at=r.expires_at)  # fmt: skip


async def create(session: AsyncSession, p: Principal, conversation_id: uuid.UUID, message_id: uuid.UUID,
                 actions: list[dict[str, Any]]) -> list[dict[str, Any]]:  # fmt: skip
    """Store the turn's recommended actions as pending proposals; returns them as the screen shows them."""
    out = []
    now = datetime.now(UTC)
    for a in actions:
        kind, payload = a.get("kind"), a.get("payload")
        if kind not in PERMISSION or not isinstance(payload, dict):
            continue
        r = AiActionProposal(user_id=p.user_id, conversation_id=conversation_id, message_id=message_id,
                             action_type=kind, label=str(a.get("label", ""))[:300], detail=a.get("detail"),
                             payload=payload, payload_hash=payload_hash(kind, payload), status="pending",
                             expires_at=now + TTL, idempotency_key=uuid.uuid4().hex)  # fmt: skip
        session.add(r)
        await session.flush()
        out.append({**_out(p, r, now).model_dump(mode="json"), "proposal_id": str(r.id)})
    return out


async def statuses(session: AsyncSession, p: Principal, conversation_id: uuid.UUID) -> dict[str, ProposalOut]:
    rows = (await session.execute(select(AiActionProposal).where(
        AiActionProposal.conversation_id == conversation_id, AiActionProposal.user_id == p.user_id))).scalars()  # fmt: skip
    return {str(r.id): _out(p, r) for r in rows}


async def _own(session: AsyncSession, p: Principal, pid: uuid.UUID, lock: bool = False) -> AiActionProposal:
    r = await session.get(AiActionProposal, pid, with_for_update=lock)
    if r is None or r.user_id != p.user_id:  # proposals are private to the user they were made for
        raise NotFound("This suggestion isn't available.")
    return r


def _check_can(p: Principal, r: AiActionProposal) -> None:
    perm = PERMISSION[r.action_type]
    if not p.can(perm):
        raise Forbidden(f"Your role ({p.role}) can't do this: it needs {NEEDS[r.action_type]}.")


# ---- re-validation against live data (shared by preview and approve) ---------------------------------------------


async def _working_plan(session: AsyncSession, plan_id: str) -> Any:
    plan = await planning.get_current(session)
    if plan is None or str(plan.id) != plan_id:
        raise DomainError(
            "The plan this was suggested for is no longer the working plan. Ask again for current fixes."
        )
    return plan


def _fix_ids(plan: Any, payload: dict[str, Any]) -> tuple[list[str], list[str]]:
    """(fixes the plan would use, the new ones); a fix must still be offered, or be an explicit night-shift window."""
    offered = {fx.id: fx for fx in plan.result.finance.fixes}
    chosen = [fx.id for fx in plan.result.finance.fixes if fx.selected]
    new = []
    for f in payload.get("fixes") or []:
        if f in chosen:
            continue
        if f not in offered and not f.startswith("night:"):
            raise DomainError(
                "This fix is no longer suggested for the plan (something changed). Ask again for current fixes."
            )
        new.append(f)
    return chosen + new, new


async def _plan_preview(
    session: AsyncSession, p: Principal, plan: Any, patch: PlanPatch
) -> tuple[list[dict[str, str]], list[str]]:
    out = await planning.update_plan(session, p.user_id, plan.id, patch, preview=True)
    if out.diff.blocked:
        raise DomainError(f"Can't apply: {out.diff.blocked}")
    from app.ai.assistant.tools import lakh

    b, w = plan.result.finance.with_, out.plan.result.finance.with_
    ob, ow = plan.result.sequence.overview, out.plan.result.sequence.overview
    rows = [{"k": "Contribution", "now": lakh(b.contribution), "then": lakh(w.contribution)},
            {"k": "Manufacturing cost", "now": lakh(b.mfg_cost), "then": lakh(w.mfg_cost)},
            {"k": "Late orders", "now": str(ob.late), "then": str(ow.late)}]  # fmt: skip
    warn = [f"{x.title}: {x.text}" for x in out.diff.worse][:3]
    return rows, warn


async def _po_body(session: AsyncSession, payload: dict[str, Any]) -> tuple[PoRaiseIn, str]:
    inv = await purchasing.inventory(session)
    m = next((x for x in inv.materials if str(x.id) == payload.get("material_id")), None)
    if m is None:
        raise DomainError("This material no longer exists.")
    try:
        q = Decimal(str(payload.get("quantity")))
    except InvalidOperation as exc:
        raise DomainError("The quantity isn't valid.") from exc
    still_short = m.shortfall is not None or m.suggested_qty > 0 or m.status == "critical_short"
    if not still_short:
        raise DomainError(f"{m.name} is no longer short: stock or deliveries on order now cover it.")
    open_po = [i for i in m.incoming if i.status == "awaiting_approval"]
    if open_po:
        raise DomainError(f"{open_po[0].po_number} for {m.name} is already waiting for the owner's approval.")
    supplier = (payload.get("supplier") or m.supplier or "").strip()
    if not supplier:
        raise DomainError(f"No usual supplier for {m.name}: raise this PO in Purchasing and choose one.")
    exp = max(
        date.fromisoformat(payload.get("expected_date") or clock.today().isoformat()),
        clock.today() + timedelta(days=1),
    )
    body = PoRaiseIn(material_id=m.id, supplier=supplier, quantity=q, price_per_unit_paise=int(payload.get("price_per_unit_paise") or m.price_per_unit_paise),
                     expected_date=exp, order_numbers=list(payload.get("order_numbers") or []),
                     note="Raised from the AI Assistant (approved by the user)")  # fmt: skip
    return body, m.unit


async def _follow_body(
    session: AsyncSession, payload: dict[str, Any], note: str | None
) -> tuple[uuid.UUID, ArFollowUpIn]:
    cid = uuid.UUID(payload["customer_id"])
    nxt = date.fromisoformat(payload["next_follow_up"]) if payload.get("next_follow_up") else None
    if nxt is not None and nxt < clock.today():
        nxt = clock.today() + timedelta(days=1)
    text = (note if note is not None else payload.get("note") or "").strip()
    if not text:
        raise DomainError("Write what the follow-up is about.")
    return cid, ArFollowUpIn(channel=payload.get("channel") or "call", note=text[:2000], next_follow_up=nxt)


async def preview(session: AsyncSession, p: Principal, pid: uuid.UUID) -> ProposalPreview:
    """What applying it would do now, re-checked against live data. Saves nothing."""
    r = await _own(session, p, pid)
    base = _out(p, r)
    if base.status != "pending":
        return ProposalPreview(proposal=base, ok=False, lines=[], rows=[], warnings=[],
                               error=f"This suggestion is {base.status}.")  # fmt: skip
    try:
        _check_can(p, r)
        lines: list[str] = []
        rows: list[dict[str, str]] = []
        warns: list[str] = []
        if r.action_type in ("plan_fix", "plan_sequence"):
            plan = await _working_plan(session, r.payload["plan_id"])
            if r.action_type == "plan_fix":
                fixes, new = _fix_ids(plan, r.payload)
                if not new:
                    lines.append(f"Already in {plan.number}: nothing to change.")
                else:
                    rows, warns = await _plan_preview(session, p, plan, PlanPatch(fixes=fixes))
                    lines.append(
                        f"Adds “{r.label}” to {plan.number} (draft, needs your approval in Planning as usual)."
                    )
            else:
                rule = r.payload.get("rule")
                if rule not in RULES:
                    raise DomainError("Unknown sequencing rule.")
                rows, warns = await _plan_preview(session, p, plan, PlanPatch(rule=rule))
                lines.append(f"Re-sequences {plan.number} by “{RULES[rule]}”.")
        elif r.action_type == "raise_po":
            body, unit = await _po_body(session, r.payload)
            lines += [f"Raises a PO: {body.quantity.normalize():f} {unit} {r.payload.get('material', '')} from {body.supplier}.",
                      f"Expected {body.expected_date:%a %-d %b}" + (f" · for {', '.join(body.order_numbers)}" if body.order_numbers else ""),
                      "It waits for the owner's approval in Purchasing before it is ordered."]  # fmt: skip
        elif r.action_type == "follow_up":
            _cid, fb = await _follow_body(session, r.payload, None)
            lines += [f"Logs a {fb.channel} follow-up with the customer: “{fb.note}”",
                      f"Next follow-up: {fb.next_follow_up:%a %-d %b}" if fb.next_follow_up else "No next follow-up date"]  # fmt: skip
        return ProposalPreview(proposal=base, ok=True, lines=lines, rows=rows, warnings=warns, error=None)
    except DomainError as exc:
        return ProposalPreview(proposal=base, ok=False, lines=[], rows=[], warnings=[], error=exc.message)


async def _execute(
    session: AsyncSession, p: Principal, r: AiActionProposal, note: str | None
) -> dict[str, Any]:
    if r.action_type in ("plan_fix", "plan_sequence"):
        plan = await _working_plan(session, r.payload["plan_id"])
        if r.action_type == "plan_fix":
            fixes, new = _fix_ids(plan, r.payload)
            if not new:
                return {"summary": f"Already in {plan.number}.", "href": f"/planning/{plan.id}?step=4"}
            patch = PlanPatch(fixes=fixes)
        else:
            if r.payload.get("rule") not in RULES:
                raise DomainError("Unknown sequencing rule.")
            patch = PlanPatch(rule=r.payload["rule"])
        before = plan.result.finance.with_.contribution
        out = await planning.update_plan(session, p.user_id, plan.id, patch, preview=False)
        from app.ai.assistant.tools import lakh

        after = out.plan.result.finance.with_.contribution
        return {"summary": f"{r.label}: applied to {plan.number} · contribution {lakh(before)} → {lakh(after)}",
                "href": f"/planning/{plan.id}?step=4"}  # fmt: skip
    if r.action_type == "raise_po":
        body, unit = await _po_body(session, r.payload)
        po = await purchasing.raise_po(session, p.user_id, body)
        return {"summary": f"{po.number} raised for {body.quantity.normalize():f} {unit} from {body.supplier} · "
                           f"waiting for the owner's approval", "href": f"/purchasing/purchase?po={po.id}"}  # fmt: skip
    if r.action_type == "follow_up":
        cid, fb = await _follow_body(session, r.payload, note)
        await ar.log_follow_up(session, p.user_id, cid, fb)
        return {"summary": f"Follow-up logged: “{fb.note}”", "href": f"/billing?customer={cid}"}
    raise DomainError("Unknown action.")


async def approve(session: AsyncSession, p: Principal, items: list[ProposalApproveItem]) -> list[ProposalOut]:
    """Execute approved proposals, each re-validated; one failing doesn't undo the others (savepoints)."""
    out = []
    for it in items:
        r = await _own(session, p, it.id, lock=True)  # row lock: a double click waits, then sees "executed"
        now = datetime.now(UTC)
        if r.status == "executed":
            out.append(_out(p, r, now))  # idempotent: never executed twice
            continue
        if r.status != "pending":
            raise DomainError(f"“{r.label}” is {r.status}.")
        if r.expires_at <= now:
            r.status = "expired"
            out.append(_out(p, r, now))
            continue
        _check_can(p, r)
        if it.payload_hash != r.payload_hash:
            raise DomainError("This suggestion changed since you reviewed it. Review it again.")
        try:
            async with session.begin_nested():
                result = await _execute(session, p, r, it.note)
            r.status, r.result = "executed", result
        except DomainError as exc:
            r.status, r.result = "failed", {"error": exc.message}
        r.decided_by, r.decided_at = p.user_id, now
        await audit.record(session, actor_id=p.user_id, action="approve", entity_type="ai_action_proposal",
                           entity_id=r.id, summary=f"AI suggestion {r.status}: {r.label}",
                           after={"status": r.status, "type": r.action_type})  # fmt: skip
        out.append(_out(p, r, now))
    return out


async def reject(session: AsyncSession, p: Principal, pid: uuid.UUID) -> ProposalOut:
    r = await _own(session, p, pid, lock=True)
    if r.status == "pending":
        r.status, r.decided_by, r.decided_at = "rejected", p.user_id, datetime.now(UTC)
        await audit.record(session, actor_id=p.user_id, action="reject", entity_type="ai_action_proposal",
                           entity_id=r.id, summary=f"AI suggestion dismissed: {r.label}")  # fmt: skip
    return _out(p, r)
