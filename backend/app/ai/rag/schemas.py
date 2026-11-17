import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class AiDocumentOut(BaseModel):
    id: uuid.UUID
    title: str
    file_name: str
    size_bytes: int
    roles: list[str]  # who may see it in answers; empty = every role
    status: str  # queued | processing | ready | failed
    error: str | None
    pages: int
    chunks: int
    embedder: str | None
    created_at: datetime
    indexed_at: datetime | None
    can_edit: bool
    url: str  # short-lived signed link to the original


class AiDocumentPatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    roles: list[str] | None = None
