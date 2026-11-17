"""Company documents for the assistant (SOPs, policies, manuals): the encrypted original and its searchable chunks.

Each chunk keeps its page, a 384-dim embedding (pgvector, HNSW cosine index) and a full-text vector (GIN), and the
name of the embedder that made it (vector search only compares chunks made by the embedder in use)."""

import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Computed, DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY, TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.core.db import Base, TenantScoped, TimestampMixin

DIM = 384


class AiDocument(Base, TenantScoped, TimestampMixin):
    __tablename__ = "ai_documents"
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200))
    file_name: Mapped[str] = mapped_column(String(255))
    file_key: Mapped[str] = mapped_column(String(500))  # encrypted with the company key
    content_type: Mapped[str] = mapped_column(String(100))
    size_bytes: Mapped[int] = mapped_column(Integer)
    sha256: Mapped[str] = mapped_column(String(64))
    # who may see it in answers: roles (empty = every role). Enforced in retrieval, before anything reaches the model.
    roles: Mapped[list[str]] = mapped_column(ARRAY(String(32)), default=list)
    status: Mapped[str] = mapped_column(String(16), default="queued")  # queued | processing | ready | failed
    error: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[int] = mapped_column(Integer, default=0)
    chunks: Mapped[int] = mapped_column(Integer, default=0)
    embedder: Mapped[str | None] = mapped_column(String(100))
    uploaded_by: Mapped[uuid.UUID] = mapped_column()
    indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class AiDocumentChunk(Base, TenantScoped):
    __tablename__ = "ai_document_chunks"
    __table_args__ = (
        Index("ix_ai_chunks_embedding", "embedding", postgresql_using="hnsw",
              postgresql_ops={"embedding": "vector_cosine_ops"}),
        Index("ix_ai_chunks_tsv", "tsv", postgresql_using="gin"),
    )  # fmt: skip
    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ai_documents.id", ondelete="CASCADE"), index=True
    )
    seq: Mapped[int] = mapped_column(Integer)
    page: Mapped[int | None] = mapped_column(
        Integer
    )  # 1-based; None when the format has no pages (DOCX, TXT)
    text: Mapped[str] = mapped_column(Text)
    embedding: Mapped[list[float]] = mapped_column(Vector(DIM))
    embedder: Mapped[str] = mapped_column(String(100))
    tsv: Mapped[str] = mapped_column(TSVECTOR, Computed("to_tsvector('english', text)", persisted=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
