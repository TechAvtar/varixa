import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.enums import AnalysisStatus, AnalysisType, StepStatus

MAX_TITLE_LENGTH = 300


class AnalysisFileLinkResponse(BaseModel):
    """Short-lived signed URL for the stored original (owner only). Never a storage key."""

    url: str
    expires_in_seconds: int
    mime_type: str | None
    width: int | None
    height: int | None


class AnalysisFileResponse(BaseModel):
    """Client-safe view of the stored original. The storage key is never exposed."""

    model_config = ConfigDict(from_attributes=True)

    original_filename: str | None
    mime_type: str | None
    size_bytes: int | None
    sha256: str
    width: int | None
    height: int | None


class AnalysisStepResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    status: StepStatus
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    error_code: str | None
    error_message: str | None
    details: dict[str, Any] | None


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: AnalysisType
    status: AnalysisStatus
    title: str | None
    error_code: str | None
    error_message: str | None
    created_at: datetime
    completed_at: datetime | None
    file: AnalysisFileResponse | None = None
    steps: list[AnalysisStepResponse] = Field(default_factory=list)


class AnalysisCreatedResponse(BaseModel):
    """Matches the API contract for creation endpoints."""

    id: uuid.UUID
    status: AnalysisStatus
    type: AnalysisType


class AnalysisListResponse(BaseModel):
    items: list[AnalysisResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)


class AnalysisCounts(BaseModel):
    total: int
    image: int
    text: int
