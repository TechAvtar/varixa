"""Report service: assemble the bundle from stored rows, render, store privately, record."""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

from PIL import Image
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.enums import AnalysisStatus
from app.models import Analysis, Report, User
from app.providers.llm.base import SECTIONS
from app.providers.storage.base import ObjectNotFoundError, ObjectStorage
from app.repositories.analysis import AnalysisRepository
from app.repositories.provider_calls import ProviderCallRepository
from app.repositories.reports import ReportRepository
from app.services import storage_keys
from app.services.authorization import assert_owns_analysis
from app.services.evidence.engine import EvidenceThresholds, ai_level
from app.services.image.provenance import NormalizedProvenance, provenance_limitations
from app.services.reports.bundle import ReportBundle, evidence_lines, forensic_methods
from app.services.reports.overview import build_overview
from app.services.reports.pdf import render_pdf
from app.services.search.summary import summarize_matches
from app.services.usage import UsageService
from app.utils.errors import ConflictError, NotFoundError, ValidationError

log = logging.getLogger("verixa.reports")

SUPPORTED_FORMATS = frozenset({"pdf"})
THUMBNAIL_MAX = 480


def _thumbnail(data: bytes) -> bytes | None:
    try:
        with Image.open(io.BytesIO(data)) as im:
            im.load()
            rgb = im.convert("RGB")
            rgb.thumbnail((THUMBNAIL_MAX, THUMBNAIL_MAX))
            out = io.BytesIO()
            rgb.save(out, format="PNG", optimize=True)
            return out.getvalue()
    except Exception:  # not an image (text analysis) or undecodable
        return None


class ReportService:
    def __init__(self, session: AsyncSession, storage: ObjectStorage, settings: Settings) -> None:
        self._db = session
        self._storage = storage
        self._settings = settings
        self._analyses = AnalysisRepository(session)
        self._reports = ReportRepository(session)

    # -- read ---------------------------------------------------------------------------------

    async def get(self, user: User, report_id: uuid.UUID) -> Report:
        report = await self._reports.get(report_id)
        if report is None:
            raise NotFoundError("Report not found.")
        analysis = await self._analyses.get(report.analysis_id)
        if analysis is None:
            raise NotFoundError("Report not found.")
        assert_owns_analysis(user, analysis)
        return report

    async def list_for_analysis(self, user: User, analysis_id: uuid.UUID) -> Sequence[Report]:
        analysis = await self._analyses.get(analysis_id)
        if analysis is None:
            raise NotFoundError("Analysis not found.")
        assert_owns_analysis(user, analysis)
        return await self._reports.list_for_analysis(analysis_id)

    async def signed_url(self, user: User, report_id: uuid.UUID) -> tuple[str, int]:
        report = await self.get(user, report_id)
        if report.status != "completed" or not report.object_key:
            raise NotFoundError("This report has no file.")
        ttl = self._settings.signed_url_ttl_seconds
        url = await self._storage.signed_url(
            report.object_key, ttl_seconds=ttl, filename=f"verixa-report-{report.id}.pdf"
        )
        return url, ttl

    # -- create -------------------------------------------------------------------------------

    async def create(self, user: User, analysis_id: uuid.UUID, *, fmt: str) -> Report:
        if fmt not in SUPPORTED_FORMATS:
            raise ValidationError(f"Unsupported report format '{fmt}'.")
        analysis = await self._analyses.get(analysis_id)
        if analysis is None:
            raise NotFoundError("Analysis not found.")
        assert_owns_analysis(user, analysis)
        if analysis.status != AnalysisStatus.COMPLETED:
            raise ConflictError(
                "The analysis has not completed; a report can only be generated from a "
                "finished analysis.",
                code="ANALYSIS_NOT_COMPLETED",
            )
        evidence = await self._analyses.list_evidence(analysis_id)
        if not evidence:
            raise ConflictError("No evidence has been generated yet.", code="NO_EVIDENCE")

        bundle = await self._bundle(analysis, evidence)
        report = Report(analysis_id=analysis_id, format=fmt, status="completed")
        try:
            data, pages = await asyncio.to_thread(render_pdf, bundle)
            key = storage_keys.report_key(user.id, analysis_id, report.id, fmt)
            await self._storage.put(key, data, content_type="application/pdf")
            report.object_key = key
            report.size_bytes = len(data)
            report.sha256 = hashlib.sha256(data).hexdigest()
            report.page_count = pages
            report.summary_json = bundle.summary_json()
            await UsageService(self._db, self._settings).record_report(user.id, len(data))
        except Exception as exc:  # the failure is recorded, never raised as a 500 with details
            log.exception("report rendering failed analysis_id=%s", analysis_id)
            report.status = "failed"
            report.error_code = "RENDER_FAILED"
            report.error_message = exc.__class__.__name__
        await self._reports.add(report)
        await self._db.commit()
        return report

    async def _bundle(self, analysis: Analysis, evidence: Sequence[Any]) -> ReportBundle:
        aid = analysis.id
        repo = self._analyses
        thresholds = EvidenceThresholds.from_settings(self._settings)
        calls = await ProviderCallRepository(self._db).list_for_analysis(aid)
        overview = build_overview(
            evidence_rows=evidence,
            steps=analysis.steps,
            provider_calls=calls,
            thresholds=thresholds,
        )

        synthesis: dict[str, Any] | None = None
        syn = await repo.get_synthesis(aid)
        if syn is not None:
            by_id = {str(e.id): str((e.details or {}).get("rule") or "") for e in evidence}
            synthesis = {
                "provider": syn.provider,
                "model": syn.model,
                "grounded": syn.grounded,
                "warnings": list(syn.warnings_json or []),
                "sections": {
                    key: {
                        "question": question,
                        "text": (syn.sections_json.get(key) or {}).get("text") or "",
                        "grounded": (syn.sections_json.get(key) or {}).get("grounded", True),
                        "rules": [
                            by_id[i]
                            for i in (syn.sections_json.get(key) or {}).get("evidence_ids") or []
                            if i in by_id
                        ],
                    }
                    for key, question in SECTIONS
                },
            }

        metadata = provenance = ai = matches = None
        provenance_notes: list[str] = []
        forensics_row = None
        maps: dict[str, bytes] = {}
        thumbnail: bytes | None = None
        file = analysis.files[0] if analysis.files else None
        if analysis.type == "image":
            md = await repo.get_metadata(aid)
            metadata = dict(md.normalized_json or {}) if md else None
            pv = await repo.get_provenance(aid)
            provenance = dict(pv.normalized_json or {}) if pv else None
            if provenance:
                try:
                    provenance_notes = provenance_limitations(NormalizedProvenance(**provenance))
                except TypeError:  # a row written by a newer/older normaliser shape
                    provenance_notes = []
            forensics_row = await repo.get_forensics(aid)
            for art in (forensics_row.artifacts_json or []) if forensics_row else []:
                key = art.get("object_key")
                method = art.get("method")
                if isinstance(key, str) and isinstance(method, str):
                    try:
                        maps[method], _ = await self._storage.get(key)
                    except ObjectNotFoundError:
                        continue
            if file is not None:
                try:
                    original, _ = await self._storage.get(file.object_key)
                    thumbnail = await asyncio.to_thread(_thumbnail, original)
                except ObjectNotFoundError:
                    thumbnail = None
        ai_row = await repo.get_ai_detection(aid)
        if ai_row is not None:
            ai = {
                "provider": ai_row.provider,
                "model": ai_row.model,
                "provider_version": ai_row.provider_version,
                "score": ai_row.score,
                "label": ai_row.label,
                "calibrated": ai_row.calibrated,
                "level": ai_level(
                    ai_row.score,
                    calibrated=ai_row.calibrated,
                    t=EvidenceThresholds(
                        ai_score_high=ai_row.threshold_high, ai_score_medium=ai_row.threshold_medium
                    ),
                ),
            }
        run, items = await repo.get_source_search(aid)
        if run is not None:
            matches = {
                "provider": run.provider,
                "version": run.provider_version,
                "searched_at": run.created_at,
                "summary": summarize_matches(items).__dict__,
                "items": [
                    {
                        "rank": m.rank,
                        "url": m.url,
                        "title": m.title,
                        "similarity": m.similarity,
                        "published_at": m.published_at,
                        "discovered_at": m.discovered_at,
                    }
                    for m in items
                ],
            }
        timeline = [
            {
                "event_type": t.event_type,
                "event_time": t.event_time,
                "raw_time": t.raw_time,
                "tz_known": t.tz_known,
                "certainty": t.certainty,
                "description": t.description,
                "source": t.source,
            }
            for t in await repo.list_timeline(aid)
        ]
        return ReportBundle(
            analysis_id=str(aid),
            analysis_type=str(analysis.type),
            title=analysis.title,
            status=str(analysis.status),
            created_at=analysis.created_at,
            generated_at=datetime.now(UTC),
            file={
                "original_filename": file.original_filename if file else None,
                "mime_type": file.mime_type if file else None,
                "size_bytes": file.size_bytes if file else None,
                "width": file.width if file else None,
                "height": file.height if file else None,
                "sha256": file.sha256 if file else None,
            },
            overview=overview,
            evidence=evidence_lines(evidence),
            synthesis=synthesis,
            metadata=metadata,
            provenance=provenance,
            provenance_limitations=provenance_notes,
            ai=ai,
            forensics=forensic_methods(forensics_row, maps),
            matches=matches,
            timeline=timeline,
            thumbnail_png=thumbnail,
            app_version=self._settings.app_version,
        )
