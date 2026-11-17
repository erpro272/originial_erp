import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class ChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    conversation_id: uuid.UUID | None = None


class ConversationOut(BaseModel):
    id: uuid.UUID
    title: str
    last_message_at: datetime


class MessageOut(BaseModel):
    id: uuid.UUID
    role: str
    content: str
    widgets: list[dict[str, Any]]
    citations: list[dict[str, Any]]
    actions: list[dict[str, Any]]
    related: list[dict[str, Any]]
    context: list[dict[str, Any]]
    tools: list[dict[str, Any]]
    error: str | None
    created_at: datetime


class ConversationDetail(ConversationOut):
    messages: list[MessageOut]


class RenameIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class AssistantStatus(BaseModel):
    mode: str  # live | mock
    model: str
    tools: list[str]  # the tools this user's role may use


class ProposalOut(BaseModel):
    """A write the assistant suggested; applied only after the user approves it."""

    id: uuid.UUID
    kind: str  # plan_fix | plan_sequence | raise_po | follow_up
    label: str
    detail: str | None
    status: str  # pending | executed | failed | rejected | expired
    allowed: bool  # the user's role may apply it
    needs: str  # what access it needs (shown when not allowed)
    payload_hash: str  # approval is bound to this exact suggestion
    editable: list[str]  # fields the user may change before applying (follow-up note)
    note: str | None
    result: dict[str, Any] | None  # summary + link, or error
    expires_at: datetime


class ProposalPreview(BaseModel):
    proposal: ProposalOut
    ok: bool
    lines: list[str]
    rows: list[dict[str, str]]  # now -> after (plan changes)
    warnings: list[str]
    error: str | None


class ProposalApproveItem(BaseModel):
    id: uuid.UUID
    payload_hash: str = Field(min_length=64, max_length=64)
    note: str | None = Field(default=None, max_length=2000)


class ProposalApproveIn(BaseModel):
    items: list[ProposalApproveItem] = Field(min_length=1, max_length=10)
