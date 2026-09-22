import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class ReportCreate(BaseModel):
    format: Literal["pdf"] = "pdf"


class ReportResponse(BaseModel):
    id: uuid.UUID
    analysis_id: uuid.UUID
    format: str
    status: Literal["completed", "failed", "expired"]
    created_at: datetime
    size_bytes: int | None
    sha256: str | None
    page_count: int | None
    summary: dict[str, Any]
    error_code: str | None
    error_message: str | None


class ReportListResponse(BaseModel):
    items: list[ReportResponse]


class ReportFileLink(BaseModel):
    """Short-lived signed URL for the rendered file; never a storage key."""

    url: str
    expires_in_seconds: int
    content_type: str
