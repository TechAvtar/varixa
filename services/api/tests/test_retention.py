"""T037: configurable retention and deletion of raw content, derived artifacts and records."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.config import Settings
from app.models import Analysis, Evidence, ProviderCall, Report
from app.services.retention import RetentionService, retention_deadline
from tests.test_image_upload import auth_headers, make_image
from tests.test_text import ENGLISH


@pytest.fixture
def mock_providers(migrated_settings: Settings) -> Settings:
    migrated_settings.ai_detector_provider = "mock"
    migrated_settings.source_search_provider = "mock"
    return migrated_settings


async def make_image_analysis(client: AsyncClient, headers: dict[str, str]) -> str:
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.jpg", make_image("JPEG", (64, 48)), "image/jpeg")},
    )
    assert r.status_code == 201, r.text
    return str(r.json()["id"])


async def sweep(client: AsyncClient, settings: Settings, now: datetime) -> dict[str, Any]:
    app = client._transport.app  # type: ignore[attr-defined]
    async with app.state.session_factory() as db:
        report = await RetentionService(db, app.state.storage, settings).run_once(now=now)
    return report.to_json()


# -- policy -------------------------------------------------------------------------------------


def test_retention_deadline_follows_setting(settings: Settings) -> None:
    created = datetime(2026, 9, 1, tzinfo=UTC)
    settings.raw_content_retention_hours = 24
    assert retention_deadline(created, settings) == created + timedelta(hours=24)
    settings.raw_content_retention_hours = 0
    assert retention_deadline(created, settings) is None


async def test_new_analyses_carry_the_retention_deadline(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})
    body = (await client.get(f"/analysis/{r.json()['id']}", headers=headers)).json()
    created = datetime.fromisoformat(body["created_at"])
    assert datetime.fromisoformat(body["retention_at"]) == created + timedelta(
        hours=migrated_settings.raw_content_retention_hours
    )
    assert body["kept_at"] is None and body["content_purged_at"] is None


# -- raw content expiry ---------------------------------------------------------------------------


async def test_content_expires_but_records_and_evidence_stay(
    client: AsyncClient, mock_providers: Settings
) -> None:
    headers = await auth_headers(client)
    aid = await make_image_analysis(client, headers)
    rep = (await client.post(f"/analysis/{aid}/report", headers=headers, json={})).json()
    original = (await client.get(f"/analysis/{aid}/file", headers=headers)).json()["url"]
    forensics = (await client.get(f"/analysis/{aid}/forensics", headers=headers)).json()
    art = next(a for a in forensics["artifacts"] if a["method"] == "ela")["url"]
    pdf = (await client.get(f"/reports/{rep['id']}/pdf", headers=headers)).json()["url"]
    for url in (original, art, pdf):
        assert (await client.get(url)).status_code == 200

    # Not yet due: nothing happens.
    before = await sweep(client, mock_providers, datetime.now(UTC))
    assert before["content_expired"] == 0
    assert (await client.get(original)).status_code == 200

    # Due: originals, derived images and report files go; everything else remains.
    later = datetime.now(UTC) + timedelta(hours=mock_providers.raw_content_retention_hours + 1)
    report = await sweep(client, mock_providers, later)
    assert report["content_expired"] == 1 and report["objects_failed"] == 0
    assert report["objects_removed"] >= 3 and report["errors"] == []
    for url in (original, art, pdf):
        assert (await client.get(url)).status_code == 404

    body = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    assert body["content_purged_at"] is not None and body["status"] == "completed"
    assert (await client.get(f"/analysis/{aid}/file", headers=headers)).status_code == 404
    assert (await client.get(f"/analysis/{aid}/forensics", headers=headers)).json()[
        "artifacts"
    ] == []
    assert (await client.get(f"/analysis/{aid}/evidence", headers=headers)).status_code == 200
    reports = (await client.get(f"/analysis/{aid}/reports", headers=headers)).json()["items"]
    assert reports[0]["status"] == "expired"
    assert (await client.get(f"/reports/{rep['id']}/pdf", headers=headers)).status_code == 404
    # A second sweep is a no-op.
    again = await sweep(client, mock_providers, later + timedelta(hours=1))
    assert again["content_expired"] == 0 and again["objects_removed"] == 0


async def test_kept_analyses_are_not_expired(client: AsyncClient, mock_providers: Settings) -> None:
    headers = await auth_headers(client)
    aid = await make_image_analysis(client, headers)
    kept = await client.post(f"/analysis/{aid}/keep", headers=headers)
    assert kept.status_code == 200 and kept.json()["kept_at"] is not None
    original = (await client.get(f"/analysis/{aid}/file", headers=headers)).json()["url"]
    later = datetime.now(UTC) + timedelta(days=30)
    assert (await sweep(client, mock_providers, later))["content_expired"] == 0
    assert (await client.get(original)).status_code == 200
    # Releasing the keep makes it eligible again.
    released = await client.delete(f"/analysis/{aid}/keep", headers=headers)
    assert released.status_code == 200 and released.json()["kept_at"] is None
    assert (await sweep(client, mock_providers, later))["content_expired"] == 1
    intruder = await auth_headers(client, "i@example.com")
    assert (await client.post(f"/analysis/{aid}/keep", headers=intruder)).status_code == 404


async def test_retention_can_be_disabled(client: AsyncClient, mock_providers: Settings) -> None:
    mock_providers.raw_content_retention_hours = 0
    headers = await auth_headers(client)
    aid = await make_image_analysis(client, headers)
    body = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    assert body["retention_at"] is None
    later = datetime.now(UTC) + timedelta(days=3650)
    assert (await sweep(client, mock_providers, later))["content_expired"] == 0


# -- provider responses ----------


async def test_provider_raw_responses_are_purged_after_the_window(
    client: AsyncClient, mock_providers: Settings
) -> None:
    headers = await auth_headers(client)
    aid = await make_image_analysis(client, headers)
    app = client._transport.app  # type: ignore[attr-defined]
    days = mock_providers.provider_response_retention_days
    assert days > 0
    assert (await sweep(client, mock_providers, datetime.now(UTC)))[
        "provider_responses_purged"
    ] == 0
    later = datetime.now(UTC) + timedelta(days=days + 1)
    purged = (await sweep(client, mock_providers, later))["provider_responses_purged"]
    assert purged >= 1
    async with app.state.session_factory() as db:
        calls = (
            (
                await db.execute(
                    select(ProviderCall).where(ProviderCall.analysis_id == uuid.UUID(aid))
                )
            )
            .scalars()
            .all()
        )
    assert calls and all(c.response_json is None and c.error_json is None for c in calls)
    assert all(c.purged_at is not None and c.provider and c.status for c in calls)
    body = (await client.get(f"/analysis/{aid}/provider-calls", headers=headers)).json()
    assert body["calls"] and all(c["response_json"] is None for c in body["calls"])


# -- deletion --------------------------------------------------------------------------------------


async def test_soft_delete_removes_content_immediately_and_purges_after_grace(
    client: AsyncClient, mock_providers: Settings
) -> None:
    headers = await auth_headers(client)
    aid = await make_image_analysis(client, headers)
    rep = (await client.post(f"/analysis/{aid}/report", headers=headers, json={})).json()
    original = (await client.get(f"/analysis/{aid}/file", headers=headers)).json()["url"]
    assert (await client.delete(f"/analysis/{aid}", headers=headers)).status_code == 204
    # 2. access revoked, 3./4. content gone
    assert (await client.get(f"/analysis/{aid}", headers=headers)).status_code == 404
    assert (await client.get(f"/reports/{rep['id']}", headers=headers)).status_code == 404
    assert (await client.get(original)).status_code == 404

    app = client._transport.app  # type: ignore[attr-defined]
    grace = mock_providers.deleted_record_grace_days
    within = await sweep(client, mock_providers, datetime.now(UTC) + timedelta(days=grace - 1))
    assert within["records_purged"] == 0
    async with app.state.session_factory() as db:
        assert (await db.get(Analysis, uuid.UUID(aid))) is not None  # still there, marked deleted

    after = await sweep(client, mock_providers, datetime.now(UTC) + timedelta(days=grace + 1))
    assert after["records_purged"] == 1
    async with app.state.session_factory() as db:
        assert (await db.get(Analysis, uuid.UUID(aid))) is None
        for model in (Evidence, ProviderCall, Report):
            rows = (
                (await db.execute(select(model).where(model.analysis_id == uuid.UUID(aid))))
                .scalars()
                .all()
            )
            assert rows == [], model.__name__


async def test_record_retention_soft_deletes_old_analyses(
    client: AsyncClient, mock_providers: Settings
) -> None:
    mock_providers.analysis_retention_days = 30
    headers = await auth_headers(client)
    aid = await make_image_analysis(client, headers)
    soon = await sweep(client, mock_providers, datetime.now(UTC) + timedelta(days=10))
    assert soon["records_soft_deleted"] == 0
    late = await sweep(client, mock_providers, datetime.now(UTC) + timedelta(days=31))
    assert late["records_soft_deleted"] == 1
    assert (await client.get(f"/analysis/{aid}", headers=headers)).status_code == 404
    listed = (await client.get("/analysis", headers=headers)).json()
    assert all(item["id"] != aid for item in listed["items"])
