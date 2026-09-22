"""Retention and deletion workflows (docs/09).

Four independent, idempotent passes, each driven by a setting:

1. **Raw content expiry** — an analysis' uploaded original, derived image artifacts and
   rendered report files are removed ``raw_content_retention_hours`` after creation,
   unless the owner *kept* the analysis. Records, evidence and the report metadata stay,
   so the report remains readable without the pictures.
2. **Provider raw responses** — ``response_json`` / ``error_json`` on provider calls
   older than ``provider_response_retention_days`` are cleared; provider, operation,
   version, status, latency and cost stay as the minimum audit trail.
3. **Deleted records** — analyses soft-deleted more than ``deleted_record_grace_days``
   ago are purged (row and every child); a structured log line is the only trace.
4. **Record retention** — when ``analysis_retention_days`` is set, live analyses older
   than that are soft-deleted (which removes their content) and later purged.

Every pass retries storage removals on the next run; nothing is ever logged that could
identify content (no keys, no titles).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import Analysis
from app.providers.storage.base import ObjectStorage
from app.repositories.analysis import AnalysisRepository
from app.repositories.provider_calls import ProviderCallRepository
from app.repositories.reports import ReportRepository

log = logging.getLogger("verixa.retention")


@dataclass
class RetentionReport:
    now: datetime
    content_expired: int = 0
    objects_removed: int = 0
    objects_failed: int = 0
    provider_responses_purged: int = 0
    records_soft_deleted: int = 0
    records_purged: int = 0
    errors: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, object]:
        return {
            "now": self.now.isoformat(),
            "content_expired": self.content_expired,
            "objects_removed": self.objects_removed,
            "objects_failed": self.objects_failed,
            "provider_responses_purged": self.provider_responses_purged,
            "records_soft_deleted": self.records_soft_deleted,
            "records_purged": self.records_purged,
            "errors": list(self.errors),
        }


def retention_deadline(created_at: datetime, settings: Settings) -> datetime | None:
    """When the raw content of an analysis created at ``created_at`` expires (None = never)."""
    hours = settings.raw_content_retention_hours
    if hours <= 0:
        return None
    return created_at + timedelta(hours=hours)


class RetentionService:
    def __init__(self, session: AsyncSession, storage: ObjectStorage, settings: Settings) -> None:
        self._db = session
        self._storage = storage
        self._settings = settings
        self._analyses = AnalysisRepository(session)
        self._calls = ProviderCallRepository(session)
        self._reports = ReportRepository(session)

    async def run_once(self, *, now: datetime | None = None, limit: int = 500) -> RetentionReport:
        now = now or datetime.now(UTC)
        report = RetentionReport(now=now)
        await self._expire_content(now, limit, report)
        await self._purge_provider_responses(now, report)
        await self._retire_old_records(now, limit, report)
        await self._purge_deleted(now, limit, report)
        log.info("retention sweep %s", report.to_json())
        return report

    # -- passes ---------------------------------------------------------------------------------

    async def remove_content(self, analysis: Analysis, report: RetentionReport) -> None:
        """Delete every stored object of an analysis (originals, artifacts, reports)."""
        for key in await self._analyses.list_object_keys(analysis.id):
            try:
                await self._storage.delete(key)
                report.objects_removed += 1
            except Exception:  # keep going; the next sweep retries
                report.objects_failed += 1

    async def _expire_content(self, now: datetime, limit: int, report: RetentionReport) -> None:
        for analysis in await self._analyses.list_content_expired(now, limit=limit):
            before_failed = report.objects_failed
            await self.remove_content(analysis, report)
            if report.objects_failed > before_failed:
                report.errors.append(f"content expiry incomplete for {analysis.id}")
                continue
            analysis.content_purged_at = now
            await self._reports.mark_expired(analysis.id, now)
            report.content_expired += 1
        await self._db.commit()

    async def _purge_provider_responses(self, now: datetime, report: RetentionReport) -> None:
        days = self._settings.provider_response_retention_days
        if days <= 0:
            return
        cutoff = now - timedelta(days=days)
        report.provider_responses_purged += await self._calls.purge_responses_before(cutoff, now)
        await self._db.commit()

    async def _retire_old_records(self, now: datetime, limit: int, report: RetentionReport) -> None:
        days = self._settings.analysis_retention_days
        if days <= 0:
            return
        cutoff = now - timedelta(days=days)
        for analysis in await self._analyses.list_live_created_before(cutoff, limit=limit):
            analysis.deleted_at = now
            await self.remove_content(analysis, report)
            analysis.content_purged_at = now
            report.records_soft_deleted += 1
        await self._db.commit()

    async def _purge_deleted(self, now: datetime, limit: int, report: RetentionReport) -> None:
        days = self._settings.deleted_record_grace_days
        cutoff = now - timedelta(days=days)
        for analysis in await self._analyses.list_deleted_before(cutoff, limit=limit):
            before_failed = report.objects_failed
            await self.remove_content(analysis, report)
            if report.objects_failed > before_failed:
                report.errors.append(f"purge deferred for {analysis.id}: storage")
                continue
            aid: uuid.UUID = analysis.id
            user_id = analysis.user_id
            await self._analyses.purge(analysis)
            # Minimum audit trail: what was purged, never what it contained.
            log.info(
                "purged analysis id=%s user_id=%s deleted_at=%s", aid, user_id, analysis.deleted_at
            )
            report.records_purged += 1
        await self._db.commit()
