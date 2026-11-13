import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.customers.schemas import CustomerIn

UploadStatus = Literal["uploaded", "extracting", "needs_review", "verified", "saved", "failed", "rejected"]


class UploadOut(BaseModel):
    id: uuid.UUID
    batch_id: uuid.UUID
    file_name: str
    doc_format: str
    size_bytes: int
    page_count: int | None
    status: UploadStatus
    error: str | None
    overall_confidence: float | None
    duplicate_flag: str
    ai_mode: str | None
    customer_action: str | None
    invoice_id: uuid.UUID | None
    uploaded_by_name: str | None
    created_at: datetime
    buyer_name: str | None = None
    invoice_number: str | None = None
    grand_total_paise: int | None = None


class RejectedFile(BaseModel):
    file_name: str
    error: str


class BatchOut(BaseModel):
    batch_id: uuid.UUID
    uploads: list[UploadOut]
    rejected: list[RejectedFile]


class UploadList(BaseModel):
    items: list[UploadOut]
    counts: dict[str, int]
    summary: dict[str, int]  # imported, matched_existing, new_customers, need_review, failed


class PageOut(BaseModel):
    number: int
    url: str


class UploadDetail(BaseModel):
    upload: UploadOut
    pages: list[PageOut]
    original_url: str
    document: dict[str, Any]  # fields/lines/qr (sensitive values masked unless allowed)
    checks: list[dict[str, Any]]
    match: dict[str, Any]
    duplicate: dict[str, Any]
    versions: int
    sensitive_visible: bool


class Draft(BaseModel):
    """User corrections: raw text per field (null clears) and the full list of lines."""

    fields: dict[str, str | None] = Field(default_factory=dict)
    lines: list[dict[str, str | None]] | None = None


class DraftSave(Draft):
    verified: bool = False


class CheckResult(BaseModel):
    document: dict[str, Any]
    checks: list[dict[str, Any]]
    match: dict[str, Any]
    duplicate: dict[str, Any]


class CustomerChoice(BaseModel):
    mode: Literal["existing", "new"]
    customer_id: uuid.UUID | None = None
    customer: CustomerIn | None = None


class SaveIn(Draft):
    customer: CustomerChoice
    acknowledged: list[str] = Field(default_factory=list, description="Ids of warnings the user accepted")
    confirm_possible_duplicate: bool = False


class SaveOut(BaseModel):
    invoice_id: uuid.UUID
    customer_id: uuid.UUID
    customer_action: Literal["existing", "new"]
    order_number: str | None


class RejectIn(BaseModel):
    reason: str = Field(min_length=3, max_length=300)
