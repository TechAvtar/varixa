"""T034: the overview groups stored evidence and explains the methodology; nothing is invented."""

import uuid
from types import SimpleNamespace as Row
from typing import Any

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.services.evidence.engine import EvidenceThresholds
from app.services.reports.overview import (
    LEVEL_DEFINITIONS,
    METHODOLOGY_NOTES,
    build_overview,
)
from tests.test_image_upload import auth_headers, make_image
from tests.test_text import ENGLISH

T = EvidenceThresholds()


def rec(level: str, kind: str = "signal", confidence: float | None = None) -> Any:
    return Row(
        id=uuid.uuid4(),
        level=level,
        confidence=confidence,
        details={"kind": kind, "rule": f"{level.lower()}.{kind}"},
    )


def test_groups_follow_level_and_kind() -> None:
    rows = [
        rec("VERIFIED", "fact", 1.0),
        rec("STRONG", "signal", 0.8),
        rec("PROBABLE", "signal", 0.9),
        rec("POSSIBLE", "signal", 0.4),
        rec("UNKNOWN", "signal"),
        rec("UNKNOWN", "unknown"),
        rec("UNKNOWN", "conflict"),
    ]
    o = build_overview(evidence_rows=rows, steps=[], provider_calls=[], thresholds=T)
    assert [r.level for r in o.verified] == ["VERIFIED"]
    assert [r.level for r in o.strong] == ["STRONG"]
    assert [r.level for r in o.probabilistic] == ["PROBABLE", "POSSIBLE"]
    assert len(o.conflicts) == 1 and len(o.unknown) == 2  # quiet signals count as unknown
    assert o.counts == {"VERIFIED": 1, "STRONG": 1, "PROBABLE": 1, "POSSIBLE": 1, "UNKNOWN": 3}
    assert o.synthesis_confidence == 0.75  # strongest record minus one conflict
    assert o.level_definitions == LEVEL_DEFINITIONS and o.methodology == METHODOLOGY_NOTES
    assert set(LEVEL_DEFINITIONS) == {"VERIFIED", "STRONG", "PROBABLE", "POSSIBLE", "UNKNOWN"}


def test_methodology_lists_steps_and_engines_from_the_audit_trail() -> None:
    steps = [
        Row(name="validate", status="completed", duration_ms=3, error_code=None),
        Row(name="ai", status="skipped", duration_ms=None, error_code=None),
        Row(name="ela", status="failed", duration_ms=12, error_code="ELA_BOOM"),
    ]

    def call(provider: str, version: str, op: str, status: str) -> Any:
        return Row(provider=provider, model_version=version, operation=op, status=status)

    calls = [
        call("exiftool", "13.59", "metadata.extract", "success"),
        call("mock", "mock-detector@0.0", "ai.detect", "cached"),
        call("mock", "mock-detector@0.0", "ai.detect", "success"),
        call("mock", "0.0", "search.image", "failed"),
    ]
    o = build_overview(evidence_rows=[], steps=steps, provider_calls=calls, thresholds=T)
    assert [(s.name, s.status, s.duration_ms, s.error_code) for s in o.steps] == [
        ("validate", "completed", 3, None),
        ("ai", "skipped", None, None),
        ("ela", "failed", 12, "ELA_BOOM"),
    ]
    by = {(e.provider, e.model_version): e for e in o.engines}
    assert by[("exiftool", "13.59")].operations == ["metadata.extract"]
    ai = by[("mock", "mock-detector@0.0")]
    assert ai.calls == 2 and ai.cached == 1 and ai.failed == 0
    assert by[("mock", "0.0")].failed == 1
    assert o.thresholds["ai_score_high"] == T.ai_score_high
    assert o.synthesis_confidence == 0.0 and o.counts["VERIFIED"] == 0


# -- API ------------------------------------------------------------------------------------------


@pytest.fixture
def mock_providers(migrated_settings: Settings) -> Settings:
    migrated_settings.ai_detector_provider = "mock"
    migrated_settings.source_search_provider = "mock"
    migrated_settings.llm_provider = "mock"
    return migrated_settings


async def test_overview_endpoint_assembles_everything(
    client: AsyncClient, mock_providers: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.jpg", make_image("JPEG", (64, 48)), "image/jpeg")},
    )
    aid = r.json()["id"]
    body = (await client.get(f"/analysis/{aid}/overview", headers=headers)).json()
    assert body["version"] == "v1" and body["generated_at"]
    assert body["verified"] and body["verified"][0]["rule"] == "file.identity"
    assert all(i["level"] in {"PROBABLE", "POSSIBLE"} for i in body["probabilistic"])
    assert all(i["level"] == "UNKNOWN" for i in body["unknown"])
    total = sum(
        len(body[g]) for g in ("verified", "strong", "probabilistic", "conflicts", "unknown")
    )
    assert total == sum(body["counts"].values())
    evidence = (await client.get(f"/analysis/{aid}/evidence", headers=headers)).json()
    assert total == len(evidence["items"])
    assert body["synthesis_confidence"] == evidence["synthesis_confidence"]
    assert body["synthesis"] is not None and body["synthesis"]["grounded"] is True
    m = body["methodology"]
    assert set(m["level_definitions"]) == {"VERIFIED", "STRONG", "PROBABLE", "POSSIBLE", "UNKNOWN"}
    assert [s["name"] for s in m["steps"]][:2] == ["validate", "hashing"]
    assert any(e["provider"] == "mock" for e in m["engines"])
    assert m["thresholds"]["conflict_penalty"] == 0.25 and m["notes"]


async def test_overview_without_synthesis_and_ownership(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    owner = await auth_headers(client, "o@example.com")
    r = await client.post("/analysis/text", headers=owner, json={"text": ENGLISH})
    aid = r.json()["id"]
    body = (await client.get(f"/analysis/{aid}/overview", headers=owner)).json()
    assert body["synthesis"] is None and body["verified"]
    assert any(
        s["name"] == "synthesis" and s["status"] == "skipped" for s in body["methodology"]["steps"]
    )
    intruder = await auth_headers(client, "i@example.com")
    assert (await client.get(f"/analysis/{aid}/overview", headers=intruder)).status_code == 404
    assert (
        await client.get(f"/analysis/{uuid.uuid4()}/overview", headers=owner)
    ).status_code == 404
    assert (await client.get(f"/analysis/{aid}/overview")).status_code == 401
