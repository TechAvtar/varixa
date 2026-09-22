"""T032: timeline events come only from recorded times, labelled with certainty and source."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace as Row
from typing import Any

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.services.evidence.engine import EvidenceThresholds, Observations, build_evidence
from app.services.evidence.timeline import LIMITATIONS, build_timeline
from tests.test_image_upload import auth_headers, make_image
from tests.test_text import ENGLISH

T = EvidenceThresholds()


def provenance(*, valid: bool, signed_at: str | None, actions: list[dict[str, Any]]) -> Any:
    return Row(
        engine="c2patool",
        engine_version="0.9",
        has_c2pa=True,
        valid_signature=valid,
        signer="Cam Co",
        signed_at=signed_at,
        claim_generator=None,
        normalized_json={"actions": actions},
    )


def metadata(captured: dict[str, Any] | None, modified: dict[str, Any] | None) -> Any:
    return Row(
        engine="exiftool",
        engine_version="13",
        software=None,
        camera_make=None,
        camera_model=None,
        normalized_json={"has_exif": True, "captured_at": captured, "modified_at": modified},
    )


def events_of(o: Observations) -> list[Any]:
    return build_timeline(o, build_evidence(o, T))


def types(events: list[Any]) -> list[str]:
    return [e.event_type for e in events]


# -- construction -------------------------------------------------------------------------------


def test_events_are_ordered_and_undated_come_last() -> None:
    o = Observations(
        "image",
        file=Row(sha256="a" * 64, mime_type="image/jpeg", width=1, height=1, size_bytes=1),
        submitted_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
        provenance=provenance(
            valid=True,
            signed_at="2026-01-05T10:00:00Z",
            actions=[
                {"action": "c2pa.created", "when": "2026-01-05T09:00:00Z", "software_agent": "Cam"},
                {"action": "c2pa.edited", "when": None},
                {"action": "c2pa.color_adjustments", "when": "not a time"},
            ],
        ),
        metadata=metadata(
            {"raw": "2026:01:05 08:59:00", "parsed": "2026-01-05T08:59:00", "tz_known": False},
            {"raw": "0000:00:00 00:00:00", "parsed": None, "tz_known": False},
        ),
    )
    events = events_of(o)
    assert types(events) == [
        "metadata.captured",
        "provenance.action:c2pa.created",
        "provenance.signed",
        "analysis.submitted",
        "provenance.action:c2pa.color_adjustments",
        "metadata.modified",
    ]
    dated = [e for e in events if e.event_time is not None]
    assert dated == sorted(dated, key=lambda e: e.event_time)
    undated = [e for e in events if e.event_time is None]
    assert [e.raw_time for e in undated] == ["not a time", "0000:00:00 00:00:00"]
    assert all(e.event_time.tzinfo is not None for e in dated)  # placeable = UTC-aware


def test_certainty_follows_the_evidence_level_and_source_is_named() -> None:
    valid = events_of(
        Observations(
            "image", provenance=provenance(valid=True, signed_at="2026-01-05T10:00:00Z", actions=[])
        )
    )
    signed = next(e for e in valid if e.event_type == "provenance.signed")
    assert signed.certainty == "VERIFIED" and signed.source == "c2pa/c2patool"
    assert signed.source_rules == ["provenance.valid"] and "Cam Co" in signed.description
    invalid = events_of(
        Observations(
            "image",
            provenance=provenance(valid=False, signed_at="2026-01-05T10:00:00Z", actions=[]),
        )
    )
    signed = next(e for e in invalid if e.event_type == "provenance.signed")
    assert signed.certainty == "POSSIBLE" and "validation reported problems" in signed.description

    meta = events_of(
        Observations(
            "image",
            metadata=metadata(
                {
                    "raw": "2026:01:05 08:59:00+01:00",
                    "parsed": "2026-01-05T08:59:00+01:00",
                    "tz_known": True,
                },
                None,
            ),
        )
    )
    cap = next(e for e in meta if e.event_type == "metadata.captured")
    assert cap.certainty == "POSSIBLE" and cap.source == "metadata/exiftool" and cap.tz_known
    assert cap.event_time == datetime(2026, 1, 5, 7, 59, tzinfo=UTC)  # converted to UTC
    assert cap.raw_time == "2026:01:05 08:59:00+01:00" and cap.source_rules == ["metadata.captured"]


def test_naive_times_are_flagged_not_silently_assumed() -> None:
    meta = events_of(
        Observations(
            "image",
            metadata=metadata(
                {"raw": "2026:01:05 08:59:00", "parsed": "2026-01-05T08:59:00", "tz_known": False},
                None,
            ),
        )
    )
    cap = next(e for e in meta if e.event_type == "metadata.captured")
    assert cap.tz_known is False and "timezone not recorded" in cap.description
    assert cap.event_time == datetime(2026, 1, 5, 8, 59, tzinfo=UTC)
    assert any("treated as UTC" in note for note in LIMITATIONS)


def test_sources_yield_publication_and_discovery_events() -> None:
    run = Row(provider="mock", provider_version="0.0")
    found = datetime(2026, 9, 2, 8, tzinfo=UTC)
    matches = [
        Row(url="https://x.invalid/a", published_at="2025-12-24", discovered_at=found),
        Row(url="https://x.invalid/b", published_at=None, discovered_at=found),
    ]
    events = events_of(Observations("image", search_run=run, search_matches=matches))
    assert types(events) == ["source.published", "source.discovered", "source.discovered"]
    pub = events[0]
    assert pub.certainty == "POSSIBLE" and pub.raw_time == "2025-12-24" and not pub.tz_known
    assert pub.data["url"] == "https://x.invalid/a" and pub.source == "search/mock@0.0"
    assert all(e.certainty == "VERIFIED" for e in events[1:])


def test_nothing_is_invented_when_nothing_is_recorded() -> None:
    assert events_of(Observations("image")) == []
    only_file = Observations(
        "text",
        file=Row(sha256="a" * 64, mime_type="text/plain", width=None, height=None, size_bytes=3),
        submitted_at=datetime(2026, 9, 1, tzinfo=UTC),
    )
    events = events_of(only_file)
    assert types(events) == ["analysis.submitted"] and events[0].certainty == "VERIFIED"


# -- pipeline + API -------------------------------------------------------------------------------


@pytest.fixture
def mock_providers(migrated_settings: Settings) -> Settings:
    migrated_settings.ai_detector_provider = "mock"
    migrated_settings.source_search_provider = "mock"
    return migrated_settings


async def test_pipeline_writes_timeline_linked_to_evidence(
    client: AsyncClient, mock_providers: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.jpg", make_image("JPEG", (64, 48)), "image/jpeg")},
    )
    aid = r.json()["id"]
    detail = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    step = next(s for s in detail["steps"] if s["name"] == "evidence")
    assert step["details"]["timeline_events"] >= 1
    body = (await client.get(f"/analysis/{aid}/timeline", headers=headers)).json()
    assert body["version"] == "v1" and body["limitations"]
    kinds = [e["event_type"] for e in body["events"]]
    assert "analysis.submitted" in kinds
    # Mock search returns matches with a discovery time -> VERIFIED discovery events.
    assert "source.discovered" in kinds
    evidence_ids = {
        i["id"]
        for i in (await client.get(f"/analysis/{aid}/evidence", headers=headers)).json()["items"]
    }
    for e in body["events"]:
        assert e["certainty"] in {"VERIFIED", "STRONG", "PROBABLE", "POSSIBLE", "UNKNOWN"}
        assert e["source"] and e["description"]
        assert set(e["source_evidence_ids"]) <= evidence_ids
    times = [e["event_time"] for e in body["events"] if e["event_time"]]
    assert times == sorted(times)


async def test_text_analyses_have_a_timeline_too(
    client: AsyncClient, mock_providers: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})
    body = (await client.get(f"/analysis/{r.json()['id']}/timeline", headers=headers)).json()
    assert [e["event_type"] for e in body["events"]][-1] in {
        "analysis.submitted",
        "source.discovered",
    }
    assert any(e["event_type"] == "analysis.submitted" for e in body["events"])


async def test_timeline_endpoint_enforces_ownership(
    client: AsyncClient, mock_providers: Settings
) -> None:
    owner = await auth_headers(client, "o@example.com")
    r = await client.post("/analysis/text", headers=owner, json={"text": ENGLISH})
    aid = r.json()["id"]
    intruder = await auth_headers(client, "i@example.com")
    assert (await client.get(f"/analysis/{aid}/timeline", headers=intruder)).status_code == 404
    assert (
        await client.get(f"/analysis/{uuid.uuid4()}/timeline", headers=owner)
    ).status_code == 404
    assert (await client.get(f"/analysis/{aid}/timeline")).status_code == 401
