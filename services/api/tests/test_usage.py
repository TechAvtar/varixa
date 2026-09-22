"""T038: usage counters, storage accounting, provider-cost tracking and limits."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.enums import ProviderCallStatus
from app.models import Analysis, User
from app.services.provider_calls import ProviderCallRecorder
from app.services.retention import RetentionService
from app.services.usage import UsageService, period_start
from tests.test_image_upload import auth_headers, make_image
from tests.test_text import ENGLISH


def test_period_is_the_first_of_the_utc_month() -> None:
    assert period_start(datetime(2026, 9, 22, 23, 59, tzinfo=UTC)).isoformat() == "2026-09-01"
    # A late-evening local time that is already next month in UTC counts for the UTC month.
    from datetime import timedelta, timezone

    late = datetime(2026, 9, 30, 23, 30, tzinfo=timezone(timedelta(hours=-2)))
    assert period_start(late).isoformat() == "2026-10-01"


async def test_counters_follow_analyses_reports_and_storage(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    migrated_settings.llm_provider = "mock"
    headers = await auth_headers(client)
    zero = (await client.get("/usage", headers=headers)).json()
    assert zero["analyses_count"] == 0 and zero["current_storage_bytes"] == 0
    assert zero["analyses_remaining"] is None and zero["storage_remaining_bytes"] is None

    img = make_image("JPEG", (64, 48))
    r = await client.post(
        "/analysis/image", headers=headers, files={"file": ("a.jpg", img, "image/jpeg")}
    )
    aid = r.json()["id"]
    await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})
    rep = (await client.post(f"/analysis/{aid}/report", headers=headers, json={})).json()

    u = (await client.get("/usage", headers=headers)).json()
    assert (u["analyses_count"], u["image_count"], u["text_count"]) == (2, 1, 1)
    assert u["reports_count"] == 1
    assert u["period_start"] == period_start().isoformat()
    # Activity bytes: the two originals plus the report, at least.
    assert u["storage_bytes_period"] >= len(img) + len(ENGLISH.encode()) + rep["size_bytes"]
    # Current occupancy: originals + report + forensic maps; drops when the analysis is deleted.
    assert u["current_storage_bytes"] >= len(img) + rep["size_bytes"]
    before = u["current_storage_bytes"]
    assert (await client.delete(f"/analysis/{aid}", headers=headers)).status_code == 204
    after = (await client.get("/usage", headers=headers)).json()
    assert after["current_storage_bytes"] < before
    assert after["analyses_count"] == 2  # activity counters never go down
    # Another user sees nothing of this.
    other = await auth_headers(client, "other@example.com")
    assert (await client.get("/usage", headers=other)).json()["analyses_count"] == 0


async def test_retention_expiry_frees_current_storage(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await auth_headers(client)
    await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.jpg", make_image("JPEG", (64, 48)), "image/jpeg")},
    )
    assert (await client.get("/usage", headers=headers)).json()["current_storage_bytes"] > 0
    app = client._transport.app  # type: ignore[attr-defined]
    later = datetime.now(UTC) + timedelta(hours=migrated_settings.raw_content_retention_hours + 1)
    async with app.state.session_factory() as db:
        await RetentionService(db, app.state.storage, migrated_settings).run_once(now=later)
    assert (await client.get("/usage", headers=headers)).json()["current_storage_bytes"] == 0


async def test_provider_cost_and_calls_are_tracked(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    migrated_settings.ai_detector_provider = "mock"
    headers = await auth_headers(client)
    r = await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})
    aid = uuid.UUID(r.json()["id"])
    u = (await client.get("/usage", headers=headers)).json()
    assert u["provider_calls_count"] >= 1 and u["provider_cost"] == 0.0  # mocks are free
    app = client._transport.app  # type: ignore[attr-defined]
    async with app.state.session_factory() as db:
        rec = ProviderCallRecorder(db)
        await rec.record(
            analysis_id=aid,
            provider="paid",
            operation="ai.detect",
            status=ProviderCallStatus.SUCCESS,
            estimated_cost=0.0125,
        )
        await rec.record(
            analysis_id=aid,
            provider="paid",
            operation="ai.detect",
            status=ProviderCallStatus.FAILED,
            estimated_cost=None,
        )
        await db.commit()
    u2 = (await client.get("/usage", headers=headers)).json()
    assert u2["provider_calls_count"] == u["provider_calls_count"] + 2
    assert u2["provider_cost"] == pytest.approx(0.0125)


# -- limits ---------------------------------------------------------------------------------------


async def test_monthly_analysis_limit_is_enforced(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    migrated_settings.usage_monthly_analysis_limit = 2
    headers = await auth_headers(client)
    for _ in range(2):
        assert (
            await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})
        ).status_code == 201
    third = await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})
    assert third.status_code == 429 and third.json()["error"]["code"] == "USAGE_LIMIT_EXCEEDED"
    u = (await client.get("/usage", headers=headers)).json()
    assert u["analyses_remaining"] == 0 and u["analysis_limit"] == 2
    # Limits are per user.
    other = await auth_headers(client, "other@example.com")
    assert (
        await client.post("/analysis/text", headers=other, json={"text": ENGLISH})
    ).status_code == 201


async def test_storage_limit_is_enforced_on_upload(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    img = make_image("JPEG", (64, 48))
    migrated_settings.usage_storage_limit_bytes = len(img) + 10
    headers = await auth_headers(client)
    first = await client.post(
        "/analysis/image", headers=headers, files={"file": ("a.jpg", img, "image/jpeg")}
    )
    assert first.status_code == 201
    second = await client.post(
        "/analysis/image", headers=headers, files={"file": ("b.jpg", img, "image/jpeg")}
    )
    assert second.status_code == 429
    assert second.json()["error"]["code"] == "STORAGE_LIMIT_EXCEEDED"
    # Deleting frees the space again.
    assert (
        await client.delete(f"/analysis/{first.json()['id']}", headers=headers)
    ).status_code == 204
    third = await client.post(
        "/analysis/image", headers=headers, files={"file": ("c.jpg", img, "image/jpeg")}
    )
    assert third.status_code == 201


async def test_provider_budget_skips_paid_steps_when_spent(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    migrated_settings.ai_detector_provider = "mock"
    migrated_settings.source_search_provider = "mock"
    migrated_settings.llm_provider = "mock"
    migrated_settings.usage_monthly_provider_cost_limit = 0.01
    headers = await auth_headers(client)
    me = (await client.get("/auth/me", headers=headers)).json()
    app = client._transport.app  # type: ignore[attr-defined]
    async with app.state.session_factory() as db:
        await UsageService(db, migrated_settings).record_provider_call(uuid.UUID(me["id"]), 0.02)
        await db.commit()
    r = await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})
    detail = (await client.get(f"/analysis/{r.json()['id']}", headers=headers)).json()
    steps = {s["name"]: s for s in detail["steps"]}
    for name in ("ai", "search", "synthesis"):
        assert steps[name]["status"] == "skipped", name
        assert "budget" in steps[name]["details"]["reason"]
    assert detail["status"] == "completed"  # deterministic evidence still ran
    u = (await client.get("/usage", headers=headers)).json()
    assert u["provider_budget_remaining"] == 0.0


async def test_history_lists_periods(client: AsyncClient, migrated_settings: Settings) -> None:
    headers = await auth_headers(client)
    await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})
    me = (await client.get("/auth/me", headers=headers)).json()
    app = client._transport.app  # type: ignore[attr-defined]
    async with app.state.session_factory() as db:
        repo = UsageService(db, migrated_settings)._usage
        await repo.increment(
            uuid.UUID(me["id"]), period_start() - timedelta(days=40), analyses_count=5
        )
        await db.commit()
    body = (await client.get("/usage/history?months=2", headers=headers)).json()
    assert [p["analyses_count"] for p in body["periods"]] == [1, 5]
    assert (await client.get("/usage")).status_code == 401
    assert (await client.get("/usage/history?months=0", headers=headers)).status_code == 422


async def test_usage_rows_belong_to_users(client: AsyncClient, migrated_settings: Settings) -> None:
    headers = await auth_headers(client)
    await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})
    app = client._transport.app  # type: ignore[attr-defined]
    from sqlalchemy import select

    from app.models import Usage

    async with app.state.session_factory() as db:
        rows = (await db.execute(select(Usage))).scalars().all()
        users = (await db.execute(select(User))).scalars().all()
        analyses = (await db.execute(select(Analysis))).scalars().all()
    assert len(rows) == 1 and rows[0].user_id == users[0].id == analyses[0].user_id
