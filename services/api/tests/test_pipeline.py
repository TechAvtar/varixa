import uuid
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.enums import AnalysisStatus, AnalysisType, StepStatus
from app.models import Analysis, AnalysisFile, AnalysisStep, User
from app.providers.storage.local import LocalObjectStorage
from app.services.analysis.pipeline import (
    PipelineContext,
    PipelineRunner,
    StepFailedError,
    StepOutcome,
)
from app.services.analysis.steps import ValidateImageStep
from app.workers import run_analysis
from tests.test_image_upload import auth_headers, make_image


class FakeStep:
    def __init__(self, name: str, *, critical: bool, behaviour: str = "ok") -> None:
        self.name = name
        self.critical = critical
        self.behaviour = behaviour
        self.ran = False

    async def run(self, ctx: PipelineContext) -> StepOutcome:
        self.ran = True
        if self.behaviour == "ok":
            return StepOutcome.ok(value=1)
        if self.behaviour == "fail":
            raise StepFailedError("BOOM", "It failed.")
        if self.behaviour == "crash":
            raise RuntimeError("secret internals " + "x" * 50)
        return StepOutcome.skipped("nothing to do")


@pytest.fixture
def storage(tmp_path: Any) -> LocalObjectStorage:
    return LocalObjectStorage(root=tmp_path / "s", secret="x" * 40, public_base_url="http://t")


async def make_ctx(
    session: AsyncSession, storage: LocalObjectStorage, settings: Settings, *, with_file: bool
) -> PipelineContext:
    user = User(email=f"{uuid.uuid4()}@example.com")
    analysis = Analysis(user=user, type=AnalysisType.IMAGE, status=AnalysisStatus.PROCESSING)
    session.add_all([user, analysis])
    await session.flush()
    file = None
    if with_file:
        data = make_image("PNG", (32, 16))
        import hashlib

        sha = hashlib.sha256(data).hexdigest()
        key = f"uploads/{user.id}/{analysis.id}/{sha}.png"
        await storage.put(key, data, content_type="image/png")
        file = AnalysisFile(analysis_id=analysis.id, object_key=key, sha256=sha)
        session.add(file)
        await session.flush()
    await session.commit()
    return PipelineContext(
        analysis=analysis, file=file, session=session, storage=storage, settings=settings
    )


async def steps_for(session: AsyncSession, analysis_id: uuid.UUID) -> list[AnalysisStep]:
    stmt = (
        select(AnalysisStep)
        .where(AnalysisStep.analysis_id == analysis_id)
        .order_by(AnalysisStep.position)
    )
    return list((await session.execute(stmt)).scalars().all())


# -- runner semantics -------------------------------------------------------------


async def test_runner_records_every_step(
    session: AsyncSession, storage: LocalObjectStorage, migrated_settings: Settings
) -> None:
    ctx = await make_ctx(session, storage, migrated_settings, with_file=False)
    steps = [FakeStep("a", critical=True), FakeStep("b", critical=False, behaviour="skip")]
    result = await PipelineRunner(steps).run(ctx)
    assert result.completed

    records = await steps_for(session, ctx.analysis.id)
    assert [(r.name, r.status, r.position) for r in records] == [
        ("a", StepStatus.COMPLETED, 0),
        ("b", StepStatus.SKIPPED, 1),
    ]
    assert records[0].details == {"value": 1}
    assert records[0].duration_ms is not None and records[0].started_at and records[0].finished_at
    assert records[1].details == {"reason": "nothing to do"}


async def test_non_critical_failure_is_isolated(
    session: AsyncSession, storage: LocalObjectStorage, migrated_settings: Settings
) -> None:
    ctx = await make_ctx(session, storage, migrated_settings, with_file=False)
    steps = [
        FakeStep("a", critical=False, behaviour="fail"),
        FakeStep("b", critical=False, behaviour="crash"),
        FakeStep("c", critical=True),
    ]
    result = await PipelineRunner(steps).run(ctx)
    assert result.completed
    assert all(s.ran for s in steps)

    records = await steps_for(session, ctx.analysis.id)
    assert records[0].status == StepStatus.FAILED and records[0].error_code == "BOOM"
    assert records[1].status == StepStatus.FAILED and records[1].error_code == "STEP_ERROR"
    assert "secret internals" not in (records[1].error_message or "")  # no internals leak
    assert records[2].status == StepStatus.COMPLETED


async def test_critical_failure_stops_pipeline_and_skips_rest(
    session: AsyncSession, storage: LocalObjectStorage, migrated_settings: Settings
) -> None:
    ctx = await make_ctx(session, storage, migrated_settings, with_file=False)
    steps = [FakeStep("a", critical=True, behaviour="fail"), FakeStep("b", critical=False)]
    result = await PipelineRunner(steps).run(ctx)
    assert not result.completed
    assert (result.failed_step, result.error_code, result.error_message) == (
        "a",
        "BOOM",
        "It failed.",
    )
    assert not steps[1].ran

    records = await steps_for(session, ctx.analysis.id)
    assert records[1].status == StepStatus.SKIPPED
    assert records[1].details == {"reason": "earlier critical step failed"}


def test_runner_rejects_duplicate_step_names() -> None:
    with pytest.raises(ValueError):
        PipelineRunner([FakeStep("a", critical=True), FakeStep("a", critical=False)])


# -- validate step ------------------------------------------------------------------


async def test_validate_step_publishes_verified_image(
    session: AsyncSession, storage: LocalObjectStorage, migrated_settings: Settings
) -> None:
    ctx = await make_ctx(session, storage, migrated_settings, with_file=True)
    outcome = await ValidateImageStep().run(ctx)
    assert outcome.status == StepStatus.COMPLETED
    assert outcome.details["format"] == "PNG" and outcome.details["width"] == 32
    assert outcome.details["frames"] == 1
    assert ctx.artifacts["image"].sha256 == ctx.file.sha256  # type: ignore[union-attr]


async def test_validate_step_detects_hash_mismatch(
    session: AsyncSession, storage: LocalObjectStorage, migrated_settings: Settings
) -> None:
    ctx = await make_ctx(session, storage, migrated_settings, with_file=True)
    assert ctx.file is not None
    await storage.put(ctx.file.object_key, make_image("PNG", (8, 8)), content_type="image/png")
    with pytest.raises(StepFailedError) as exc:
        await ValidateImageStep().run(ctx)
    assert exc.value.code == "HASH_MISMATCH"


async def test_validate_step_reports_missing_file(
    session: AsyncSession, storage: LocalObjectStorage, migrated_settings: Settings
) -> None:
    ctx = await make_ctx(session, storage, migrated_settings, with_file=True)
    assert ctx.file is not None
    await storage.delete(ctx.file.object_key)
    with pytest.raises(StepFailedError) as exc:
        await ValidateImageStep().run(ctx)
    assert exc.value.code == "FILE_MISSING"

    ctx.file = None
    with pytest.raises(StepFailedError) as exc:
        await ValidateImageStep().run(ctx)
    assert exc.value.code == "NO_FILE"


# -- worker + API -------------------------------------------------------------------


async def test_upload_runs_pipeline_to_completion(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.png", make_image("PNG"), "image/png")},
    )
    assert r.status_code == 201
    # ASGITransport runs background tasks before returning, so the pipeline has finished.
    detail = (await client.get(f"/analysis/{r.json()['id']}", headers=headers)).json()
    assert detail["status"] == "completed"
    assert detail["completed_at"] is not None
    assert [s["name"] for s in detail["steps"]] == [
        "validate",
        "hashing",
        "metadata",
        "provenance",
        "ela",
        "compression",
        "resampling",
        "noise",
        "ai",
        "search",
    ]
    assert all(s["status"] == "completed" for s in detail["steps"][:3])
    assert detail["steps"][0]["details"]["sha256"] == detail["file"]["sha256"]
    assert detail["steps"][0]["duration_ms"] is not None
    hashes = detail["steps"][1]["details"]
    assert hashes["sha256"] == detail["file"]["sha256"]
    assert all(len(hashes[k]) == 16 for k in ("ahash", "dhash", "phash"))
    assert len(hashes["md5"]) == 32


async def test_worker_fails_analysis_when_original_vanishes(client: AsyncClient) -> None:
    """Simulates storage loss between upload and processing."""
    headers = await auth_headers(client)
    app = client._transport.app  # type: ignore[attr-defined]
    settings: Settings = app.dependency_overrides[get_settings]()

    async with app.state.session_factory() as db:
        from app.services.analysis import AnalysisService

        user = (await db.execute(select(User))).scalars().first()
        svc = AnalysisService(db, app.state.storage, settings)
        analysis = await svc.create_image_analysis(
            user, data=make_image("JPEG"), filename="lost.jpg", title=None
        )
        analysis_id = analysis.id
        await db.refresh(analysis, ["files"])
        await app.state.storage.delete(analysis.files[0].object_key)

    await run_analysis(analysis_id, app.state.session_factory, app.state.storage, settings)

    detail = (await client.get(f"/analysis/{analysis_id}", headers=headers)).json()
    assert detail["status"] == "failed"
    assert detail["error_code"] == "FILE_MISSING"
    assert detail["steps"][0]["status"] == "failed"


async def test_worker_ignores_non_queued_analyses(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.png", make_image("PNG"), "image/png")},
    )
    analysis_id = uuid.UUID(r.json()["id"])
    app = client._transport.app  # type: ignore[attr-defined]
    settings: Settings = app.dependency_overrides[get_settings]()
    # Already completed by the background task; a second run must be a no-op.
    await run_analysis(analysis_id, app.state.session_factory, app.state.storage, settings)
    detail = (await client.get(f"/analysis/{analysis_id}", headers=headers)).json()
    assert detail["status"] == "completed" and len(detail["steps"]) == 10
