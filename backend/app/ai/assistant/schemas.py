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
