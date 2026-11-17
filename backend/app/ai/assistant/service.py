"""Conversations (private to their user) and the chat turn: persist the question, run the graph, stream typed SSE
events, persist the answer with its widgets / related records / context cards / recommended actions."""

import json
import logging
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.assistant.graph import GRAPH, HISTORY, SYSTEM, entities
from app.ai.assistant.models import AiConversation, AiMessage
from app.ai.assistant.schemas import ConversationDetail, ConversationOut, MessageOut
from app.ai.assistant.tools import Ctx, ToolOut, allowed
from app.ai.llm import get_llm
from app.core import audit, clock
from app.core.auth import Principal
from app.core.db import tenant_session
from app.core.errors import NotFound

log = logging.getLogger(__name__)
SCHEMA_VERSION = 1


def _msg(m: AiMessage) -> MessageOut:
    return MessageOut(id=m.id, role=m.role, content=m.content, widgets=m.widgets or [], citations=m.citations or [],
                      actions=m.actions or [], related=m.related or [], context=m.context or [], tools=m.tools or [],
                      error=m.error, created_at=m.created_at)  # fmt: skip


async def _own(session: AsyncSession, p: Principal, cid: uuid.UUID) -> AiConversation:
    c = await session.get(AiConversation, cid)
    if c is None or c.user_id != p.user_id or c.deleted_at is not None:
        raise NotFound("Conversation not found.")
    return c


async def list_conversations(session: AsyncSession, p: Principal, q: str | None) -> list[ConversationOut]:
    stmt = (select(AiConversation).where(AiConversation.user_id == p.user_id, AiConversation.deleted_at.is_(None))
            .order_by(AiConversation.last_message_at.desc()).limit(200))  # fmt: skip
    if q and q.strip():
        like = f"%{q.strip()}%"
        hit = select(AiMessage.conversation_id).where(AiMessage.content.ilike(like))
        stmt = stmt.where(AiConversation.title.ilike(like) | AiConversation.id.in_(hit))
    return [ConversationOut(id=c.id, title=c.title, last_message_at=c.last_message_at)
            for c in (await session.execute(stmt)).scalars()]  # fmt: skip


async def get_conversation(session: AsyncSession, p: Principal, cid: uuid.UUID) -> ConversationDetail:
    c = await _own(session, p, cid)
    msgs = (await session.execute(select(AiMessage).where(AiMessage.conversation_id == cid)
                                  .order_by(AiMessage.created_at, AiMessage.role.desc()))).scalars()  # fmt: skip
    return ConversationDetail(
        id=c.id, title=c.title, last_message_at=c.last_message_at, messages=[_msg(m) for m in msgs]
    )


async def rename(session: AsyncSession, p: Principal, cid: uuid.UUID, title: str) -> ConversationOut:
    c = await _own(session, p, cid)
    c.title = title.strip()
    return ConversationOut(id=c.id, title=c.title, last_message_at=c.last_message_at)


async def delete(session: AsyncSession, p: Principal, cid: uuid.UUID) -> None:
    c = await _own(session, p, cid)
    c.deleted_at = datetime.now(UTC)
    await audit.record(session, actor_id=p.user_id, action="delete", entity_type="ai_conversation", entity_id=c.id,
                       summary=f"Assistant conversation deleted: {c.title}")  # fmt: skip


def _sse(seq: list[int], mid: uuid.UUID | None, kind: str, data: dict[str, Any]) -> str:
    seq[0] += 1
    body = {
        "schema_version": SCHEMA_VERSION,
        "message_id": str(mid) if mid else None,
        "sequence": seq[0],
        **data,
    }
    return f"event: {kind}\ndata: {json.dumps(body, default=str, ensure_ascii=False)}\n\n"


def _merge(outs: list[ToolOut]) -> dict[str, list[dict[str, Any]]]:
    widgets, related, context, actions, citations = [], [], [], [], []
    seen_r: set[str] = set()
    seen_c: set[str] = set()
    seen_a: set[str] = set()
    for o in outs:
        widgets += o.widgets
        for r in o.related:
            k = f"{r.get('kind')}:{r.get('label')}"
            if k not in seen_r:
                seen_r.add(k)
                related.append(r)
        for cc in o.context:
            k = f"{cc.get('kind')}:{cc.get('key')}"
            if k not in seen_c:
                seen_c.add(k)
                context.append(cc)
        citations += [c for c in o.citations if c not in citations]
        for a in o.actions:
            if a["id"] not in seen_a:
                seen_a.add(a["id"])
                actions.append(a)
    return {"widgets": widgets[:12], "related": related[:10], "context": context[:4], "actions": actions[:6],
            "citations": citations[:6]}  # fmt: skip


async def chat(p: Principal, role: str, text: str, cid: uuid.UUID | None) -> AsyncIterator[str]:
    """One turn as a stream of typed SSE events. Short transactions only (none open while the model thinks)."""
    seq = [0]
    text = text.strip()
    async with tenant_session(p.tenant_id) as s:
        if cid is not None:
            conv = await _own(s, p, cid)
        else:
            conv = AiConversation(user_id=p.user_id, title=text[:80])
            s.add(conv)
            await s.flush()
        prior = list((await s.execute(
            select(AiMessage).where(AiMessage.conversation_id == conv.id, AiMessage.error.is_(None))
            .order_by(AiMessage.created_at.desc()).limit(HISTORY)
        )).scalars())[::-1]  # fmt: skip
        um = AiMessage(conversation_id=conv.id, role="user", content=text)
        s.add(um)
        conv.last_message_at = datetime.now(UTC)
        await s.flush()
        conv_id, conv_title = conv.id, conv.title
    am_id = uuid.uuid4()
    yield _sse(
        seq,
        am_id,
        "start",
        {"conversation_id": str(conv_id), "title": conv_title, "user_message_id": str(um.id)},
    )

    tools = allowed(p)
    today = clock.today()
    hints = entities(text)
    system = SYSTEM.format(today=f"{today:%A %d %B %Y}", role=role)
    if hints:
        system += f"\nMentioned in the question: {', '.join(hints)}."
    messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
    messages += [{"role": m.role, "content": m.content} for m in prior if m.content]
    messages.append({"role": "user", "content": text})
    llm = get_llm()
    state: dict[str, Any] = {}
    error: str | None = None
    try:
        async for mode, chunk in GRAPH.astream(
            {"messages": messages, "tools": tools, "ctx": Ctx(principal=p, today=today), "llm": llm, "rounds": 0,
             "outs": [], "runs": []},
            stream_mode=["custom", "values"],
        ):  # fmt: skip
            if mode == "custom":
                kind = chunk.pop("type")
                yield _sse(seq, am_id, kind, chunk)
            else:
                state = chunk
    except Exception:
        log.exception("assistant turn failed")
        error = "Something went wrong while answering. Please try again."
    merged = _merge(state.get("outs") or [])
    answer = (state.get("answer") or "").strip() if not error else ""
    if error:
        yield _sse(seq, am_id, "error", {"message": error})
    else:
        for w in merged["widgets"]:
            yield _sse(seq, am_id, "ui_widget", {"widget": w})
        words = answer.split(" ")
        for i in range(0, len(words), 6):  # streamed in small pieces
            yield _sse(
                seq,
                am_id,
                "token",
                {"text": " ".join(words[i : i + 6]) + (" " if i + 6 < len(words) else "")},
            )
        if merged["actions"]:
            # proposals are only executed after approval (handover C); for now they're recommendations
            yield _sse(seq, am_id, "approval_required", {"actions": merged["actions"], "enabled": False})
        if merged["citations"]:
            yield _sse(seq, am_id, "citations", {"citations": merged["citations"]})
        if merged["related"]:
            yield _sse(seq, am_id, "related_records", {"records": merged["related"]})
        if merged["context"]:
            yield _sse(seq, am_id, "context_update", {"cards": merged["context"]})
    async with tenant_session(p.tenant_id) as s:
        s.add(AiMessage(id=am_id, conversation_id=conv_id, role="assistant", content=answer, error=error,
                        widgets=merged["widgets"], related=merged["related"], context=merged["context"],
                        actions=merged["actions"], citations=merged["citations"], tools=state.get("runs") or [],
                        model=state.get("model") or llm.mode))  # fmt: skip
        c = await s.get(AiConversation, conv_id)
        if c is not None:
            c.last_message_at = datetime.now(UTC)
    yield _sse(seq, am_id, "done", {"conversation_id": str(conv_id), "mode": llm.mode})
