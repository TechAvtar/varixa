import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.enums import AnalysisStatus, AnalysisType


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


class AnalysisListResponse(BaseModel):
    items: list[AnalysisResponse]
    page: int = Field(ge=1)
    page_size: int = Field(ge=1)
    total: int = Field(ge=0)


class AnalysisCounts(BaseModel):
    total: int
    image: int
    text: int
