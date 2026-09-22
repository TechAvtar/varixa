"""Step-oriented processing pipeline.

Each step is independently identifiable and persisted as an ``AnalysisStep``.
Steps are isolated: an exception in a non-critical step is recorded and the
pipeline continues; a failed critical step fails the whole analysis. Steps
never raise past the runner, and the runner never logs raw content.
"""

import logging
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.enums import StepStatus
from app.models import Analysis, AnalysisFile, AnalysisStep
from app.providers.storage.base import ObjectStorage
from app.repositories.analysis import AnalysisRepository
from app.utils.errors import AppError

log = logging.getLogger("verixa.pipeline")

MAX_STEP_ERROR = 1000


@dataclass
class PipelineContext:
    """Shared, in-memory state for one pipeline run. Steps may add to ``artifacts``."""

    analysis: Analysis
    file: AnalysisFile | None
    session: AsyncSession
    storage: ObjectStorage
    settings: Settings
    artifacts: dict[str, Any] = field(default_factory=dict)
    # External engines/adapters injected by the worker, keyed by role (e.g. "metadata").
    providers: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StepOutcome:
    status: StepStatus
    details: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    error_message: str | None = None

    @classmethod
    def ok(cls, **details: Any) -> "StepOutcome":
        return cls(StepStatus.COMPLETED, details)

    @classmethod
    def skipped(cls, reason: str, **details: Any) -> "StepOutcome":
        return cls(StepStatus.SKIPPED, {"reason": reason, **details})

    @classmethod
    def failed(cls, code: str, message: str, **details: Any) -> "StepOutcome":
        return cls(StepStatus.FAILED, details, code, message[:MAX_STEP_ERROR])


class PipelineStep(Protocol):
    name: str
    critical: bool

    async def run(self, ctx: PipelineContext) -> StepOutcome: ...


class StepFailedError(Exception):
    """Raised by a step to fail with a stable code; any other exception maps to STEP_ERROR."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class PipelineResult:
    completed: bool
    failed_step: str | None = None
    error_code: str | None = None
    error_message: str | None = None


class PipelineRunner:
    def __init__(self, steps: Sequence[PipelineStep]) -> None:
        names = [s.name for s in steps]
        if len(set(names)) != len(names):
            raise ValueError("pipeline step names must be unique")
        self._steps = list(steps)

    @property
    def step_names(self) -> list[str]:
        return [s.name for s in self._steps]

    async def run(self, ctx: PipelineContext) -> PipelineResult:
        repo = AnalysisRepository(ctx.session)
        result = PipelineResult(completed=True)

        for position, step in enumerate(self._steps):
            record = AnalysisStep(
                analysis_id=ctx.analysis.id,
                name=step.name,
                position=position,
                status=StepStatus.RUNNING,
                started_at=datetime.now(UTC),
            )
            await repo.add_step(record)
            await ctx.session.commit()

            if not result.completed:
                # A critical step already failed: mark the rest as skipped, don't run them.
                outcome = StepOutcome.skipped("earlier critical step failed")
            else:
                outcome = await self._execute(step, ctx)

            self._finish(record, outcome)
            await ctx.session.commit()

            if outcome.status == StepStatus.FAILED and step.critical and result.completed:
                result = PipelineResult(
                    completed=False,
                    failed_step=step.name,
                    error_code=outcome.error_code,
                    error_message=outcome.error_message,
                )
        return result

    @staticmethod
    async def _execute(step: PipelineStep, ctx: PipelineContext) -> StepOutcome:
        started = time.perf_counter()
        try:
            outcome = await step.run(ctx)
        except StepFailedError as exc:
            outcome = StepOutcome.failed(exc.code, exc.message)
        except AppError as exc:
            outcome = StepOutcome.failed(exc.code, exc.message)
        except Exception:
            # Full traceback to the log (no content), generic message to the record.
            log.exception("step crashed analysis_id=%s step=%s", ctx.analysis.id, step.name)
            outcome = StepOutcome.failed("STEP_ERROR", "The step failed unexpectedly.")
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        return StepOutcome(
            outcome.status,
            {**outcome.details, "_elapsed_ms": elapsed_ms},
            outcome.error_code,
            outcome.error_message,
        )

    @staticmethod
    def _finish(record: AnalysisStep, outcome: StepOutcome) -> None:
        details = dict(outcome.details)
        elapsed = details.pop("_elapsed_ms", None)
        record.status = outcome.status
        record.finished_at = datetime.now(UTC)
        record.duration_ms = elapsed
        record.error_code = outcome.error_code
        record.error_message = outcome.error_message
        record.details = details or None
