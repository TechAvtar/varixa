import uuid
from typing import Annotated

from fastapi import APIRouter, File, Form, Query, UploadFile, status

from app.api.deps import AnalysisSvc, AppSettings, CurrentUser, Jobs
from app.models import Analysis
from app.schemas.analysis import (
    MAX_TITLE_LENGTH,
    AnalysisCounts,
    AnalysisCreatedResponse,
    AnalysisFileResponse,
    AnalysisListResponse,
    AnalysisResponse,
    AnalysisStepResponse,
)
from app.services.image import ImageTooLargeError

router = APIRouter(prefix="/analysis")

MAX_PAGE_SIZE = 100
_CHUNK = 1024 * 1024


async def _read_capped(upload: UploadFile, max_bytes: int) -> bytes:
    """Read the upload without ever buffering more than the cap (+1 byte to detect overflow)."""
    chunks: list[bytes] = []
    total = 0
    while chunk := await upload.read(_CHUNK):
        total += len(chunk)
        if total > max_bytes:
            raise ImageTooLargeError(
                f"The file exceeds the maximum upload size of {max_bytes // (1024 * 1024)} MB."
            )
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/image", response_model=AnalysisCreatedResponse, status_code=status.HTTP_201_CREATED)
async def create_image_analysis(
    user: CurrentUser,
    analyses: AnalysisSvc,
    settings: AppSettings,
    jobs: Jobs,
    file: Annotated[UploadFile, File()],
    title: Annotated[str | None, Form(max_length=MAX_TITLE_LENGTH)] = None,
) -> AnalysisCreatedResponse:
    """Accept one image (JPEG/PNG/WebP/TIFF). Filename and MIME are treated as untrusted."""
    data = await _read_capped(file, settings.max_upload_bytes)
    analysis = await analyses.create_image_analysis(
        user, data=data, filename=file.filename, title=title
    )
    jobs.dispatch(analysis.id)
    return AnalysisCreatedResponse(id=analysis.id, status=analysis.status, type=analysis.type)


@router.get("", response_model=AnalysisListResponse)
async def list_analyses(
    user: CurrentUser,
    analyses: AnalysisSvc,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=MAX_PAGE_SIZE),
) -> AnalysisListResponse:
    items, total = await analyses.list_owned(user, page=page, page_size=page_size)
    return AnalysisListResponse(
        items=[_to_response(a) for a in items], page=page, page_size=page_size, total=total
    )


@router.get("/counts", response_model=AnalysisCounts)
async def analysis_counts(user: CurrentUser, analyses: AnalysisSvc) -> AnalysisCounts:
    return AnalysisCounts(**await analyses.counts(user))


@router.get("/{analysis_id}", response_model=AnalysisResponse)
async def get_analysis(
    analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc
) -> AnalysisResponse:
    return _to_response(await analyses.get_owned(user, analysis_id))


@router.delete("/{analysis_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_analysis(analysis_id: uuid.UUID, user: CurrentUser, analyses: AnalysisSvc) -> None:
    await analyses.soft_delete(user, analysis_id)


def _to_response(analysis: Analysis) -> AnalysisResponse:
    response = AnalysisResponse.model_validate(analysis)
    if analysis.files:
        response.file = AnalysisFileResponse.model_validate(analysis.files[0])
    response.steps = [AnalysisStepResponse.model_validate(s) for s in analysis.steps]
    return response
