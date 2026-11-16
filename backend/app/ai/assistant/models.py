"""AI Assistant: conversations, messages (text + structured widgets / citations / actions / related records) and
action proposals (write actions the assistant suggests; executed only after the user approves, handover C)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base, TenantScoped, TimestampMixin


class AiConversation(Base, TenantScoped, TimestampMixin):
    """One chat thread. Private to the user who started it (and to their company, by RLS)."""

    __tablename__ = "ai_conversations"
    __table_args__ = (Index("ix_ai_conversations_user", "tenant_id", "user_id", "last_message_at"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    title: Mapped[str] = mapped_column(String(200))
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiMessage(Base, TenantScoped):
    __tablename__ = "ai_messages"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("ai_conversations.id"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user | assistant
    content: Mapped[str] = mapped_column(Text, default="")
    widgets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    citations: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    actions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # recommended actions
    related: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # related records chips
    context: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # ERP context cards
    tools: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # tool runs: name, ok, ms
    model: Mapped[str | None] = mapped_column(String(100))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class AiActionProposal(Base, TenantScoped, TimestampMixin):
    """A write the assistant proposed. Executed only after an authorised user approves it, after re-checking live
    data; `payload_hash` binds the approval to what was reviewed, `idempotency_key` prevents double execution."""

    __tablename__ = "ai_action_proposals"
    __table_args__ = (UniqueConstraint("tenant_id", "idempotency_key"),)
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(index=True)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_conversations.id"))
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("ai_messages.id"))
    action_type: Mapped[str] = mapped_column(String(40))
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
    payload_hash: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(
        String(16), default="pending"
    )  # pending|approved|rejected|expired|executed|failed
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    idempotency_key: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    decided_by: Mapped[uuid.UUID | None] = mapped_column()
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
