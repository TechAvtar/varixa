"""Report endpoints: create an export for an analysis, read its metadata, fetch a signed link."""

import uuid

from fastapi import APIRouter, status

from app.api.deps import CurrentUser, ReportSvc
from app.models import Report
from app.schemas.report import ReportCreate, ReportFileLink, ReportListResponse, ReportResponse

router = APIRouter()


def to_response(r: Report) -> ReportResponse:
    return ReportResponse(
        id=r.id,
        analysis_id=r.analysis_id,
        format=r.format,
        status=r.status if r.status in ("completed", "expired") else "failed",
        created_at=r.created_at,
        size_bytes=r.size_bytes,
        sha256=r.sha256,
        page_count=r.page_count,
        summary=r.summary_json or {},
        error_code=r.error_code,
        error_message=r.error_message,
    )


@router.post(
    "/analysis/{analysis_id}/report",
    response_model=ReportResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_report(
    analysis_id: uuid.UUID, body: ReportCreate, user: CurrentUser, reports: ReportSvc
) -> ReportResponse:
    """Render an export of a completed analysis and store it privately (owner only)."""
    return to_response(await reports.create(user, analysis_id, fmt=body.format))


@router.get("/analysis/{analysis_id}/reports", response_model=ReportListResponse)
async def list_reports(
    analysis_id: uuid.UUID, user: CurrentUser, reports: ReportSvc
) -> ReportListResponse:
    return ReportListResponse(
        items=[to_response(r) for r in await reports.list_for_analysis(user, analysis_id)]
    )


@router.get("/reports/{report_id}", response_model=ReportResponse)
async def get_report(report_id: uuid.UUID, user: CurrentUser, reports: ReportSvc) -> ReportResponse:
    return to_response(await reports.get(user, report_id))


@router.get("/reports/{report_id}/pdf", response_model=ReportFileLink)
async def get_report_pdf(
    report_id: uuid.UUID, user: CurrentUser, reports: ReportSvc
) -> ReportFileLink:
    """A short-lived signed link to the PDF (the download itself needs no session)."""
    url, ttl = await reports.signed_url(user, report_id)
    return ReportFileLink(url=url, expires_in_seconds=ttl, content_type="application/pdf")
