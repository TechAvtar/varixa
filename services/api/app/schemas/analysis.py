import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import AnalysisStatus, AnalysisType

MAX_TITLE_LENGTH = 300


class AnalysisFileResponse(BaseModel):
    """Client-safe view of the stored original. The storage key is never exposed."""

    model_config = ConfigDict(from_attributes=True)

    original_filename: str | None
    mime_type: str | None
    size_bytes: int | None
    sha256: str
    width: int | None
    height: int | None


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
