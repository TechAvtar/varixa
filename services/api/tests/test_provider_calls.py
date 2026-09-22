import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.enums import ProviderCallStatus
from app.models import Analysis, User
from app.repositories.provider_calls import ProviderCallRepository
from app.services.provider_calls import ProviderCallRecorder, request_hash
from tests.test_image_upload import auth_headers, make_image
from tests.test_text import ENGLISH


async def make_analysis(session: AsyncSession) -> Analysis:
    user = User(email=f"{uuid.uuid4()}@example.com")
    analysis = Analysis(user=user, type="image", status="processing")
    session.add_all([user, analysis])
    await session.commit()
    return analysis


# -- recorder ---------------------------------------------------------------------------------


def test_request_hash_is_content_sha256_only() -> None:
    assert request_hash(b"abc") == request_hash("abc")
    assert len(request_hash("abc")) == 64 and request_hash("abc") != request_hash("abd")


async def test_track_records_success_with_latency_and_fields(session: AsyncSession) -> None:
    analysis = await make_analysis(session)
    rec = ProviderCallRecorder(session)
    async with rec.track(
        analysis_id=analysis.id, provider="p", operation="detect", request_hash="h" * 64
    ) as call:
        call.model_version = "m@1"
        call.request_id = "req-1"
        call.estimated_cost = 0.0025
        call.response = {"score": 0.4}
    await session.commit()

    rows = await ProviderCallRepository(session).list_for_analysis(analysis.id)
    assert len(rows) == 1
    r = rows[0]
    assert (r.provider, r.operation, r.status) == ("p", "detect", ProviderCallStatus.SUCCESS)
    assert r.model_version == "m@1" and r.request_id == "req-1"
    assert r.latency_ms is not None and r.latency_ms >= 0
    assert float(r.estimated_cost or 0) == pytest.approx(0.0025)
    assert r.request_hash == "h" * 64 and r.response_json == {"score": 0.4} and r.error_json is None


async def test_track_records_failure_and_timeout_without_swallowing(session: AsyncSession) -> None:
    analysis = await make_analysis(session)
    rec = ProviderCallRecorder(session)
    with pytest.raises(RuntimeError):
        async with rec.track(analysis_id=analysis.id, provider="p", operation="op") as call:
            call.model_version = "m@2"
            raise RuntimeError("secret token abc123 leaked?")
    with pytest.raises(TimeoutError):
        async with rec.track(analysis_id=analysis.id, provider="p", operation="op"):
            raise TimeoutError("took too long")
    await session.commit()

    rows = await ProviderCallRepository(session).list_for_analysis(analysis.id)
    assert [r.status for r in rows] == [ProviderCallStatus.FAILED, ProviderCallStatus.TIMEOUT]
    assert rows[0].error_json == {"type": "RuntimeError", "message": "secret token abc123 leaked?"}
    assert rows[0].model_version == "m@2" and rows[0].response_json is None
    assert rows[1].error_json is not None and rows[1].error_json["type"] == "TimeoutError"


async def test_large_payloads_are_bounded(session: AsyncSession) -> None:
    analysis = await make_analysis(session)
    rec = ProviderCallRecorder(session)
    await rec.record(
        analysis_id=analysis.id,
        provider="p",
        operation="op",
        status=ProviderCallStatus.SUCCESS,
        response={"blob": "x" * 200_000},
    )
    await session.commit()
    row = (await ProviderCallRepository(session).list_for_analysis(analysis.id))[0]
    assert row.response_json is not None and row.response_json["_truncated"] is True
    assert len(row.response_json["_preview"]) <= 2048


async def test_total_cost_sums_per_analysis(session: AsyncSession) -> None:
    analysis = await make_analysis(session)
    rec = ProviderCallRecorder(session)
    for cost in (0.001, 0.002, None):
        await rec.record(
            analysis_id=analysis.id,
            provider="p",
            operation="op",
            status=ProviderCallStatus.SUCCESS,
            estimated_cost=cost,
        )
    await session.commit()
    total = await ProviderCallRepository(session).total_cost_for_analysis(analysis.id)
    assert total == pytest.approx(0.003)


# -- pipeline integration + API ----------------------------------------------------------------


@pytest.fixture
def mock_providers(migrated_settings: Settings) -> Settings:
    migrated_settings.ai_detector_provider = "mock"
    migrated_settings.source_search_provider = "mock"
    return migrated_settings


async def test_pipeline_records_every_provider_call(
    client: AsyncClient, mock_providers: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.png", make_image("PNG"), "image/png")},
    )
    aid = r.json()["id"]
    body = (await client.get(f"/analysis/{aid}/provider-calls", headers=headers)).json()
    ops = {(c["provider"], c["operation"]) for c in body["calls"]}
    assert ("mock", "ai.detect") in ops and ("mock", "search.image") in ops
    # Local engines are audited too (exiftool/pillow, c2patool when installed).
    assert any(c["operation"] == "metadata.extract" for c in body["calls"])
    for c in body["calls"]:
        assert c["status"] in ("success", "cached", "failed", "timeout", "skipped")
        assert c["latency_ms"] is None or c["latency_ms"] >= 0
        assert c["created_at"]
    ai_call = next(c for c in body["calls"] if c["operation"] == "ai.detect")
    assert ai_call["request_hash"] and len(ai_call["request_hash"]) == 64
    assert ai_call["model_version"] == "mock-detector@0.0"
    assert ai_call["response_json"]["score"] is not None
    assert body["total_estimated_cost"] == pytest.approx(0.0)  # mocks are free


async def test_cached_detection_is_recorded_as_cached(
    client: AsyncClient, mock_providers: Settings
) -> None:
    headers = await auth_headers(client)
    data = make_image("JPEG", (17, 19))
    await client.post(
        "/analysis/image", headers=headers, files={"file": ("a.jpg", data, "image/jpeg")}
    )
    second = await client.post(
        "/analysis/image", headers=headers, files={"file": ("b.jpg", data, "image/jpeg")}
    )
    body = (
        await client.get(f"/analysis/{second.json()['id']}/provider-calls", headers=headers)
    ).json()
    ai_call = next(c for c in body["calls"] if c["operation"] == "ai.detect")
    assert ai_call["status"] == "cached"
    assert ai_call["latency_ms"] is not None and ai_call["latency_ms"] < 1000  # a lookup, no call
    assert ai_call["estimated_cost"] == 0


async def test_text_pipeline_records_search_with_phrase_count(
    client: AsyncClient, mock_providers: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})
    body = (await client.get(f"/analysis/{r.json()['id']}/provider-calls", headers=headers)).json()
    search = next(c for c in body["calls"] if c["operation"] == "search.text")
    assert search["status"] == "success"
    assert search["response_json"]["queried_phrases"] >= 1


async def test_provider_calls_endpoint_enforces_ownership(
    client: AsyncClient, mock_providers: Settings
) -> None:
    owner = await auth_headers(client, "o@example.com")
    r = await client.post("/analysis/text", headers=owner, json={"text": ENGLISH})
    aid = r.json()["id"]
    intruder = await auth_headers(client, "i@example.com")
    assert (
        await client.get(f"/analysis/{aid}/provider-calls", headers=intruder)
    ).status_code == 404
    missing = await client.get(f"/analysis/{uuid.uuid4()}/provider-calls", headers=owner)
    assert missing.status_code == 404
    assert (await client.get(f"/analysis/{aid}/provider-calls")).status_code == 401
