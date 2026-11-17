import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.ai.assistant import actions, service
from app.ai.assistant.schemas import (
    AssistantStatus,
    ChatIn,
    ConversationDetail,
    ConversationOut,
    ProposalApproveIn,
    ProposalOut,
    ProposalPreview,
    RenameIn,
)
from app.ai.assistant.tools import allowed
from app.ai.llm import get_llm
from app.core.auth import Principal, TenantDB, require
from app.core.config import get_settings
from app.core.permissions import Permission

router = APIRouter(prefix="/ai", tags=["ai"])
User = Annotated[Principal, Depends(require(Permission.AI_USE))]


@router.get("/status", response_model=AssistantStatus)
async def status(p: User) -> AssistantStatus:
    llm = get_llm()
    return AssistantStatus(mode=llm.mode, model=get_settings().llm_primary_model if llm.mode == "live" else "mock",
                           tools=[t.name for t in allowed(p)])  # fmt: skip


@router.post("/chat")
async def chat(body: ChatIn, db: TenantDB, p: User) -> StreamingResponse:
    """One turn, streamed as typed Server-Sent Events: start, tool_start, tool_result, ui_widget, token,
    approval_required, related_records, context_update, error, done."""
    if body.conversation_id is not None:  # 404 before the stream starts (not someone else's conversation)
        await service.get_conversation(db, p, body.conversation_id)
    return StreamingResponse(service.chat(p, str(p.role), body.message, body.conversation_id),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})  # fmt: skip


@router.get("/conversations", response_model=list[ConversationOut])
async def conversations(db: TenantDB, p: User, q: str | None = None) -> list[ConversationOut]:
    return await service.list_conversations(db, p, q)


@router.get("/conversations/{cid}", response_model=ConversationDetail)
async def conversation(cid: uuid.UUID, db: TenantDB, p: User) -> ConversationDetail:
    return await service.get_conversation(db, p, cid)


@router.patch("/conversations/{cid}", response_model=ConversationOut)
async def rename(cid: uuid.UUID, body: RenameIn, db: TenantDB, p: User) -> ConversationOut:
    return await service.rename(db, p, cid, body.title)


@router.delete("/conversations/{cid}", status_code=204)
async def delete(cid: uuid.UUID, db: TenantDB, p: User) -> None:
    await service.delete(db, p, cid)


@router.post("/proposals/{pid}/preview", response_model=ProposalPreview)
async def preview_proposal(pid: uuid.UUID, db: TenantDB, p: User) -> ProposalPreview:
    """What applying a suggestion would do now (re-checked against live data). Saves nothing."""
    return await actions.preview(db, p, pid)


@router.post("/proposals/approve", response_model=list[ProposalOut])
async def approve_proposals(body: ProposalApproveIn, db: TenantDB, p: User) -> list[ProposalOut]:
    """Apply approved suggestions: same user, the action's permission, the reviewed payload; re-validated, executed
    once (idempotent), audited."""
    return await actions.approve(db, p, body.items)


@router.post("/proposals/{pid}/reject", response_model=ProposalOut)
async def reject_proposal(pid: uuid.UUID, db: TenantDB, p: User) -> ProposalOut:
    return await actions.reject(db, p, pid)
