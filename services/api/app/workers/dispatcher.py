"""Runs analysis pipelines outside the request/response cycle.

MVP executes jobs in-process right after the HTTP response (FastAPI background
tasks). The ``Dispatcher`` interface is the seam for a real queue later; callers
never depend on how or where the job runs.
"""

import logging
import uuid
from datetime import timedelta
from typing import Protocol

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.enums import AnalysisStatus, AnalysisType
from app.providers.ai import build_ai_detector
from app.providers.cache import InMemoryProviderCache, ProviderResultCache
from app.providers.llm import build_synthesizer
from app.providers.metadata import build_metadata_extractor
from app.providers.provenance import build_provenance_inspector
from app.providers.search import build_image_source_search, build_text_source_search
from app.providers.storage.base import ObjectStorage
from app.repositories.analysis import AnalysisRepository
from app.repositories.provider_cache import DbProviderCache
from app.services.analysis.pipeline import PipelineContext, PipelineRunner
from app.services.analysis.service import AnalysisService
from app.services.analysis.steps import image_pipeline_steps
from app.services.analysis.text_steps import text_pipeline_steps
from app.utils.metrics import registry
from app.utils.observability import analysis_id_var

log = logging.getLogger("verixa.worker")


class Dispatcher(Protocol):
    def dispatch(self, analysis_id: uuid.UUID) -> None: ...


class BackgroundTaskDispatcher:
    """Schedules ``run_analysis`` after the current response is sent."""

    def __init__(
        self,
        tasks: BackgroundTasks,
        session_factory: async_sessionmaker[AsyncSession],
        storage: ObjectStorage,
        settings: Settings,
    ) -> None:
        self._tasks = tasks
        self._session_factory = session_factory
        self._storage = storage
        self._settings = settings

    def dispatch(self, analysis_id: uuid.UUID) -> None:
        self._tasks.add_task(
            run_analysis, analysis_id, self._session_factory, self._storage, self._settings
        )


class NullDispatcher:
    """Records dispatches without running anything (tests, dry runs)."""

    def __init__(self) -> None:
        self.dispatched: list[uuid.UUID] = []

    def dispatch(self, analysis_id: uuid.UUID) -> None:
        self.dispatched.append(analysis_id)


async def run_analysis(
    analysis_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    settings: Settings,
) -> None:
    """Execute the pipeline for one analysis with its own DB session. Never raises."""
    token = analysis_id_var.set(str(analysis_id))
    try:
        await _run_analysis(analysis_id, session_factory, storage, settings)
    finally:
        analysis_id_var.reset(token)


def _finished(analysis_type: str, status: str, *, failed_step: str | None = None) -> None:
    registry.record_analysis(type=analysis_type, status=status)
    log.info(
        "analysis finished",
        extra={"type": analysis_type, "status": status, "failed_step": failed_step},
    )


async def _run_analysis(
    analysis_id: uuid.UUID,
    session_factory: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    settings: Settings,
) -> None:
    async with session_factory() as session:
        repo = AnalysisRepository(session)
        service = AnalysisService(session, storage, settings)
        analysis = await repo.get(analysis_id)
        if analysis is None or analysis.status != AnalysisStatus.QUEUED:
            log.info("skip dispatch analysis_id=%s (missing or not queued)", analysis_id)
            return
        if analysis.type == AnalysisType.IMAGE:
            steps = image_pipeline_steps()
        elif analysis.type == AnalysisType.TEXT:
            steps = text_pipeline_steps()
        else:
            await service.mark_failed(
                analysis, code="UNSUPPORTED_TYPE", message="No pipeline exists for this type."
            )
            return

        await service.mark_processing(analysis)
        cache: ProviderResultCache = (
            DbProviderCache(session, ttl=timedelta(hours=settings.provider_cache_ttl_hours))
            if settings.provider_cache_ttl_hours > 0
            else InMemoryProviderCache(ttl=timedelta(0))
        )
        ctx = PipelineContext(
            analysis=analysis,
            file=analysis.files[0] if analysis.files else None,
            session=session,
            storage=storage,
            settings=settings,
            providers={
                "metadata": build_metadata_extractor(settings),
                "provenance": build_provenance_inspector(settings),
                "ai_detector": build_ai_detector(settings, cache=cache),
                "image_search": build_image_source_search(settings, cache=cache),
                "text_search": build_text_source_search(settings, cache=cache),
                "synthesizer": build_synthesizer(settings, cache=cache),
            },
        )
        try:
            result = await PipelineRunner(steps).run(ctx)
        except Exception:
            log.exception("pipeline crashed analysis_id=%s", analysis_id)
            await service.mark_failed(
                analysis, code="PIPELINE_ERROR", message="Processing failed unexpectedly."
            )
            _finished(str(analysis.type), "failed", failed_step="pipeline")
            return

        if result.completed:
            await service.mark_completed(analysis)
            _finished(str(analysis.type), "completed")
        else:
            await service.mark_failed(
                analysis,
                code=result.error_code or "STEP_FAILED",
                message=result.error_message or f"Step '{result.failed_step}' failed.",
            )
            _finished(str(analysis.type), "failed", failed_step=result.failed_step)
