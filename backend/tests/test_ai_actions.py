"""AI Assistant actions (handover C): suggestions are stored proposals; nothing changes until the user approves.
Approval = same user + the action's permission + the reviewed payload hash; re-validated against live data, executed
once through the owning module (idempotent), one failure doesn't undo the others, statuses persist."""

from typing import Any

from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.ai.assistant import actions
from app.core.auth import Principal
from app.core.config import get_settings
from app.core.db import tenant_session
from app.core.permissions import Role
from tests.conftest import headers_for
from tests.test_ai_assistant import ask
from tests.test_purchasing import _demo_co

PROPOSALS = "/ai/proposals"


def acts(evs: list[tuple[str, dict[str, Any]]]) -> list[dict[str, Any]]:
    return next((d["actions"] for k, d in evs if k == "approval_required"), [])


async def approve(client: AsyncClient, h: dict[str, str], *items: dict[str, Any]) -> Any:
    return await client.post(f"{PROPOSALS}/approve", json={"items": list(items)}, headers=h)


async def test_follow_up_suggestion_is_applied_once_after_approval(client: AsyncClient) -> None:
    co = await _demo_co("act1")
    owner = await headers_for(client, co)
    evs = await ask(client, owner, "What do customers owe us?")
    fus = acts(evs)
    assert fus and all(a["kind"] == "follow_up" and a["status"] == "pending" and a["allowed"] for a in fus)
    a = fus[0]
    cid = next(d for k, d in evs if k == "start")["conversation_id"]
    # nothing happened yet: review first (re-checked, saves nothing)
    pv = (await client.post(f"{PROPOSALS}/{a['id']}/preview", headers=owner)).json()
    assert pv["ok"] and "follow-up" in pv["lines"][0] and pv["proposal"]["editable"] == ["note"]

    # bound to what was reviewed
    bad = await approve(client, owner, {"id": a["id"], "payload_hash": "0" * 64})
    assert bad.status_code == 400 and "changed since you reviewed" in bad.text
    # private to the user it was made for, and to the company
    planner = await headers_for(client, co, "planner")
    assert (await client.post(f"{PROPOSALS}/{a['id']}/preview", headers=planner)).status_code == 404
    other = await headers_for(client, await _demo_co("act1b"))
    assert (
        await approve(client, other, {"id": a["id"], "payload_hash": a["payload_hash"]})
    ).status_code == 404

    r = await approve(
        client, owner, {"id": a["id"], "payload_hash": a["payload_hash"], "note": "Called: paying Friday."}
    )
    assert r.status_code == 200, r.text
    done = r.json()[0]
    assert done["status"] == "executed" and "Called: paying Friday." in done["result"]["summary"]
    customer = done["result"]["href"].split("customer=")[1]
    ar = (await client.get(f"/billing/receivables/customers/{customer}", headers=owner)).json()
    logged = [i for i in ar["interactions"] if i["summary"] == "Called: paying Friday."]
    assert len(logged) == 1

    # approving again (double click, retry) returns the same result and does nothing more
    again = (await approve(client, owner, {"id": a["id"], "payload_hash": a["payload_hash"]})).json()[0]
    assert again["status"] == "executed" and again["result"] == done["result"]
    ar = (await client.get(f"/billing/receivables/customers/{customer}", headers=owner)).json()
    assert len([i for i in ar["interactions"] if i["summary"] == "Called: paying Friday."]) == 1

    # dismiss another; reopening the conversation shows the live statuses
    assert (await client.post(f"{PROPOSALS}/{fus[1]['id']}/reject", headers=owner)).json()[
        "status"
    ] == "rejected"
    conv = (await client.get(f"/ai/conversations/{cid}", headers=owner)).json()
    statuses = {x["id"]: x["status"] for x in conv["messages"][1]["actions"]}
    assert (
        statuses[a["id"]] == "executed"
        and statuses[fus[1]["id"]] == "rejected"
        and statuses[fus[2]["id"]] == "pending"
    )


async def test_plan_fix_needs_planning_edit_access_and_is_applied_to_the_working_plan(
    client: AsyncClient,
) -> None:
    co = await _demo_co("act2")
    purchaser = await headers_for(client, co, "purchaser")
    evs = await ask(client, purchaser, "Suggest fixes to improve the plan's contribution")
    fixes = acts(evs)
    assert fixes and all(
        a["kind"] == "plan_fix" and not a["allowed"] and a["needs"] == "Planning edit access" for a in fixes
    )
    r = await approve(client, purchaser, {"id": fixes[0]["id"], "payload_hash": fixes[0]["payload_hash"]})
    assert r.status_code == 403

    planner = await headers_for(client, co, "planner")
    fixes = acts(await ask(client, planner, "Suggest fixes to improve the plan's contribution"))
    assert fixes and fixes[0]["allowed"]
    f = fixes[0]
    pv = (await client.post(f"{PROPOSALS}/{f['id']}/preview", headers=planner)).json()
    assert pv["ok"] and {r["k"] for r in pv["rows"]} >= {"Contribution", "Late orders"}
    plan_before = (await client.get("/planning/plan", headers=planner)).json()
    assert not any(
        x["selected"] for x in plan_before["result"]["finance"]["fixes"] if x["label"] == f["label"]
    )
    out = (await approve(client, planner, {"id": f["id"], "payload_hash": f["payload_hash"]})).json()[0]
    assert out["status"] == "executed" and out["result"]["href"].startswith("/planning/")
    plan = (await client.get("/planning/plan", headers=planner)).json()
    assert any(x["selected"] for x in plan["result"]["finance"]["fixes"] if x["label"] == f["label"])


async def _proposal(
    tenant_id: Any, user_id: Any, role: Role, items: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    import uuid

    from app.ai.assistant.models import AiConversation, AiMessage

    p = Principal(user_id=user_id, tenant_id=tenant_id, role=role)
    async with tenant_session(tenant_id) as s:
        conv = AiConversation(user_id=user_id, title="test")
        s.add(conv)
        await s.flush()
        mid = uuid.uuid4()
        s.add(AiMessage(id=mid, conversation_id=conv.id, role="assistant", content=""))
        await s.flush()
        return await actions.create(s, p, conv.id, mid, items)


async def test_purchase_order_is_revalidated_and_one_failure_keeps_the_others(client: AsyncClient) -> None:
    co = await _demo_co("act3")
    owner = await headers_for(client, co)
    me = (await client.get("/auth/me", headers=owner)).json()
    inv = (await client.get("/purchasing/inventory", headers=owner)).json()
    short = next(m for m in inv["materials"] if m["status"] == "critical_short")
    fine = next(m for m in inv["materials"] if m["status"] == "adequate" and not m["needs"])

    def po(m: dict[str, Any]) -> dict[str, Any]:
        return {"id": f"po:{m['id']}", "kind": "raise_po", "label": f"Raise a PO for {m['name']}", "detail": "",
                "payload": {"material_id": m["id"], "material": m["name"], "quantity": "1.5", "unit": m["unit"],
                            "supplier": m["supplier"] or "Test Steels", "price_per_unit_paise": m["price_per_unit_paise"],
                            "expected_date": "2026-11-20", "order_numbers": []}}  # fmt: skip

    import uuid

    good, stale = await _proposal(co.id, uuid.UUID(me["id"]), Role.OWNER, [po(short), po(fine)])
    pv = (await client.post(f"{PROPOSALS}/{stale['id']}/preview", headers=owner)).json()
    assert not pv["ok"] and "no longer short" in pv["error"]
    out = (await approve(client, owner, {"id": good["id"], "payload_hash": good["payload_hash"]},
                         {"id": stale["id"], "payload_hash": stale["payload_hash"]})).json()  # fmt: skip
    by = {o["id"]: o for o in out}
    assert (
        by[good["id"]]["status"] == "executed"
        and "waiting for the owner's approval" in by[good["id"]]["result"]["summary"]
    )
    assert by[stale["id"]]["status"] == "failed" and "no longer short" in by[stale["id"]]["result"]["error"]
    pos = (await client.get("/purchasing/purchases", headers=owner)).json()
    assert any(p["status"] == "awaiting_approval" and p["note"] == "Raised from the AI Assistant (approved by the user)"
               for p in pos["purchase_orders"])  # fmt: skip

    # the same suggestion again: a PO already waits for approval -> refused, nothing duplicated
    (again,) = await _proposal(co.id, uuid.UUID(me["id"]), Role.OWNER, [po(short)])
    res = (await approve(client, owner, {"id": again["id"], "payload_hash": again["payload_hash"]})).json()[0]
    assert res["status"] == "failed" and "already waiting" in res["result"]["error"]

    # expired suggestions can't be applied
    (old,) = await _proposal(co.id, uuid.UUID(me["id"]), Role.OWNER, [po(short)])
    eng = create_async_engine(get_settings().database_owner_url)
    async with async_sessionmaker(eng)() as s, s.begin():
        await s.execute(text("UPDATE ai_action_proposals SET expires_at = now() - interval '1 hour' WHERE id = :i"),
                        {"i": old["id"]})  # fmt: skip
    await eng.dispose()
    res = (await approve(client, owner, {"id": old["id"], "payload_hash": old["payload_hash"]})).json()[0]
    assert res["status"] == "expired"
