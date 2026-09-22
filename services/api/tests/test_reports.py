"""T036: PDF export contains every section, is stored privately, and is owner-only."""

import base64
import contextlib
import re
import uuid
import zlib
from datetime import UTC, datetime
from types import SimpleNamespace as Row
from typing import Any

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.services.evidence.engine import EvidenceThresholds
from app.services.reports.bundle import (
    EvidenceLine,
    ForensicMethod,
    ReportBundle,
    evidence_lines,
    forensic_methods,
)
from app.services.reports.overview import build_overview
from app.services.reports.pdf import render_pdf
from tests.test_image_upload import auth_headers, make_image
from tests.test_text import ENGLISH

_STREAM = re.compile(rb"stream\r?\n(.*?)endstream", re.S)
# PDF string operands: a backslash escapes the next byte, so "(a \(b\))" is one string.
_PDF_STRING = rb"\(((?:\\.|[^\\)])*)\)"
_TJ = re.compile(_PDF_STRING + rb"\s*Tj")
_TJ_ARRAY = re.compile(rb"\[(.*?)\]\s*TJ", re.S)
_STR = re.compile(_PDF_STRING)


def _unescape(raw: bytes) -> str:
    return raw.replace(rb"\(", b"(").replace(rb"\)", b")").decode("latin-1")


def pdf_text(data: bytes) -> str:
    """Crude text extraction: decode every content stream and join the string operands.

    ReportLab writes ASCII85-encoded streams (``~>`` terminated), optionally deflated.
    """
    out: list[str] = []
    for m in _STREAM.finditer(data):
        raw = m.group(1).strip()
        if raw.endswith(b"~>"):
            with contextlib.suppress(ValueError):
                raw = base64.a85decode(raw, adobe=True)
        with contextlib.suppress(zlib.error):
            raw = zlib.decompress(raw)
        out.extend(_unescape(x) for x in _TJ.findall(raw))
        for arr in _TJ_ARRAY.findall(raw):
            out.extend(_unescape(x) for x in _STR.findall(arr))
    return " ".join(out)


def evidence_row(rule: str, level: str, claim: str, kind: str = "signal") -> Any:
    return Row(
        id=uuid.uuid4(),
        level=level,
        category=rule.split(".")[0],
        claim=claim,
        source="test",
        confidence=0.4 if level == "POSSIBLE" else None,
        details={"rule": rule, "kind": kind, "limitation": "a limitation"},
        created_at=datetime(2026, 9, 1, tzinfo=UTC),
    )


SECTION_VERIFIED = {
    "question": "What is directly verified?",
    "text": "The bytes are hashed.",
    "grounded": True,
    "rules": ["file.identity"],
}
MATCH_ITEM = {
    "rank": 1,
    "url": "https://x.invalid/a",
    "title": "A page",
    "similarity": 0.9,
    "published_at": None,
    "discovered_at": datetime(2026, 9, 1, 13, tzinfo=UTC),
}
TIMELINE_EVENT = {
    "event_type": "metadata.captured",
    "event_time": datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC),
    "raw_time": "2026:01:02 03:04:05",
    "tz_known": False,
    "certainty": "POSSIBLE",
    "description": "Capture time recorded in metadata.",
    "source": "metadata/exiftool",
}


def sample_bundle() -> ReportBundle:
    rows = [
        evidence_row("file.identity", "VERIFIED", "The stored file is image/jpeg", "fact"),
        evidence_row("metadata.software", "STRONG", 'Metadata records the software "GIMP"'),
        evidence_row("forensics.ela.anomaly", "POSSIBLE", "ELA shows 1 localised region"),
        evidence_row("provenance.absent", "UNKNOWN", "No content credentials", "unknown"),
        evidence_row("conflict.x", "UNKNOWN", "Evidence conflicts here", "conflict"),
    ]
    steps = [Row(name="validate", status="completed", duration_ms=2, error_code=None)]
    calls = [
        Row(provider="exiftool", model_version="13", operation="metadata.extract", status="success")
    ]
    overview = build_overview(
        evidence_rows=rows, steps=steps, provider_calls=calls, thresholds=EvidenceThresholds()
    )
    forensics = Row(
        ela_json={
            "applicable": True,
            "anomaly": True,
            "observation": "ELA observation text",
            "confidence": "low",
            "limitations": ["ELA limitation"],
            "version": "v1",
        },
        compression_json={"applicable": False, "reason": "not a JPEG"},
        resampling_json=None,
        noise_json=None,
        copy_move_json=None,
    )
    return ReportBundle(
        analysis_id="11111111-1111-1111-1111-111111111111",
        analysis_type="image",
        title="Sample report",
        status="completed",
        created_at=datetime(2026, 9, 1, 12, tzinfo=UTC),
        generated_at=datetime(2026, 9, 2, 8, tzinfo=UTC),
        file={
            "original_filename": "photo.jpg",
            "mime_type": "image/jpeg",
            "size_bytes": 1234,
            "width": 10,
            "height": 20,
            "sha256": "ab" * 32,
        },
        overview=overview,
        evidence=evidence_lines(rows),
        synthesis={
            "provider": "mock",
            "model": "m",
            "grounded": True,
            "warnings": [],
            "sections": {"verified": SECTION_VERIFIED},
        },
        metadata={
            "engine": "exiftool",
            "engine_version": "13",
            "has_exif": True,
            "software": "GIMP",
            "captured_at": {"raw": "2026:01:02 03:04:05"},
            "gps_present": False,
        },
        provenance={
            "engine": "c2patool",
            "engine_version": "0.9",
            "has_c2pa": False,
            "valid_signature": None,
        },
        ai={
            "provider": "mock",
            "model": "d",
            "provider_version": "0",
            "score": 0.65,
            "label": "uncertain",
            "calibrated": False,
            "level": "POSSIBLE",
        },
        forensics=forensic_methods(forensics, {"ela": make_image("PNG", (8, 8))}),
        matches={
            "provider": "mock",
            "version": "0.0",
            "searched_at": datetime(2026, 9, 1, 13, tzinfo=UTC),
            "summary": {"match_count": 1, "domain_count": 1, "earliest_published_at": None},
            "items": [MATCH_ITEM],
        },
        timeline=[TIMELINE_EVENT],
        thumbnail_png=make_image("PNG", (16, 12)),
        app_version="test",
    )


# -- rendering ----------


def test_pdf_contains_every_section_and_no_invented_text() -> None:
    data, pages = render_pdf(sample_bundle())
    assert data.startswith(b"%PDF-") and pages >= 3
    text = pdf_text(data)
    for expected in (
        "Verixa content forensics report",
        "Sample report",
        "11111111-1111-1111-1111-111111111111",
        "Summary",
        "What is directly verified?",
        "Verified facts",
        "Strong evidence",
        "Probabilistic signals",
        "Conflicts",
        "Unknown",
        "GIMP",
        "Metadata",
        "Provenance (C2PA)",
        "AI-generation signal",
        "Forensics",
        "ELA observation text",
        "not a JPEG",
        "Source matches",
        "x.invalid",
        "Timeline",
        "tz not recorded",
        "Methodology and limitations",
        "exiftool",
        "not a legal conclusion",
    ):
        assert expected in text, expected
    assert "VERIFIED" in text and "POSSIBLE" in text and "STRONG" in text


def test_pdf_renders_without_optional_parts() -> None:
    b = sample_bundle()
    bare = ReportBundle(
        **{
            **b.__dict__,
            "synthesis": None,
            "metadata": None,
            "provenance": None,
            "ai": None,
            "forensics": [],
            "matches": None,
            "timeline": [],
            "thumbnail_png": None,
            "analysis_type": "text",
        }
    )
    data, pages = render_pdf(bare)
    text = pdf_text(data)
    assert pages >= 2 and "No language-model synthesis" in text
    assert "Not applicable to text" in text and "No source search was performed" in text


def test_bundle_summary_and_forensic_mapping() -> None:
    b = sample_bundle()
    s = b.summary_json()
    assert s["counts"]["VERIFIED"] == 1 and s["conflicts"] == 1 and s["synthesis"] is True
    assert s["forensic_methods"] == ["ela"] and s["matches"] == 1 and s["timeline_events"] == 1
    ela = next(m for m in b.forensics if m.name == "ela")
    assert isinstance(ela, ForensicMethod) and ela.flagged and ela.map_png
    comp = next(m for m in b.forensics if m.name == "compression")
    assert not comp.applicable and comp.observation == "not a JPEG"
    assert all(isinstance(e, EvidenceLine) for e in b.evidence)


# -- API ----------


@pytest.fixture
def mock_providers(migrated_settings: Settings) -> Settings:
    migrated_settings.ai_detector_provider = "mock"
    migrated_settings.source_search_provider = "mock"
    migrated_settings.llm_provider = "mock"
    return migrated_settings


async def test_create_list_fetch_and_download_report(
    client: AsyncClient, mock_providers: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.jpg", make_image("JPEG", (64, 48)), "image/jpeg")},
    )
    aid = r.json()["id"]
    created = await client.post(f"/analysis/{aid}/report", headers=headers, json={"format": "pdf"})
    assert created.status_code == 201, created.text
    rep = created.json()
    assert rep["status"] == "completed" and rep["format"] == "pdf" and rep["page_count"] >= 3
    assert rep["size_bytes"] > 1000 and len(rep["sha256"]) == 64
    assert rep["summary"]["evidence_records"] > 5 and rep["summary"]["synthesis"] is True

    listed = (await client.get(f"/analysis/{aid}/reports", headers=headers)).json()["items"]
    assert [x["id"] for x in listed] == [rep["id"]]
    meta = (await client.get(f"/reports/{rep['id']}", headers=headers)).json()
    assert meta["analysis_id"] == aid and "object_key" not in meta

    link = (await client.get(f"/reports/{rep['id']}/pdf", headers=headers)).json()
    assert link["content_type"] == "application/pdf" and "sig=" in link["url"]
    pdf = await client.get(link["url"])
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    assert pdf.headers["content-type"].startswith("application/pdf")
    text = pdf_text(pdf.content)
    assert aid in text and "Forensics" in text and "Methodology and limitations" in text
    # Raw uploaded content is never embedded as bytes; a thumbnail is a re-encoded PNG.
    assert make_image("JPEG", (64, 48)) not in pdf.content


async def test_report_requires_completed_analysis_and_ownership(
    client: AsyncClient, mock_providers: Settings
) -> None:
    owner = await auth_headers(client, "o@example.com")
    r = await client.post("/analysis/text", headers=owner, json={"text": ENGLISH})
    aid = r.json()["id"]
    created = await client.post(f"/analysis/{aid}/report", headers=owner, json={"format": "pdf"})
    assert created.status_code == 201
    rid = created.json()["id"]
    intruder = await auth_headers(client, "i@example.com")
    foreign = await client.post(f"/analysis/{aid}/report", headers=intruder, json={})
    assert foreign.status_code == 404
    assert (await client.get(f"/reports/{rid}", headers=intruder)).status_code == 404
    assert (await client.get(f"/reports/{rid}/pdf", headers=intruder)).status_code == 404
    assert (await client.get(f"/analysis/{aid}/reports", headers=intruder)).status_code == 404
    assert (await client.get(f"/reports/{rid}")).status_code == 401
    assert (await client.get(f"/reports/{uuid.uuid4()}", headers=owner)).status_code == 404
    bad = await client.post(f"/analysis/{aid}/report", headers=owner, json={"format": "docx"})
    assert bad.status_code == 422


async def test_report_on_unfinished_analysis_is_a_conflict(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    from sqlalchemy import update

    from app.models import Analysis

    headers = await auth_headers(client)
    r = await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})
    aid = r.json()["id"]
    app = client._transport.app  # type: ignore[attr-defined]
    async with app.state.session_factory() as db:
        await db.execute(
            update(Analysis).where(Analysis.id == uuid.UUID(aid)).values(status="processing")
        )
        await db.commit()
    res = await client.post(f"/analysis/{aid}/report", headers=headers, json={"format": "pdf"})
    assert res.status_code == 409 and res.json()["error"]["code"] == "ANALYSIS_NOT_COMPLETED"


async def test_deleting_the_analysis_removes_the_report_file(
    client: AsyncClient, mock_providers: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})
    aid = r.json()["id"]
    rid = (await client.post(f"/analysis/{aid}/report", headers=headers, json={})).json()["id"]
    url = (await client.get(f"/reports/{rid}/pdf", headers=headers)).json()["url"]
    assert (await client.get(url)).status_code == 200
    assert (await client.delete(f"/analysis/{aid}", headers=headers)).status_code == 204
    assert (await client.get(url)).status_code == 404
    assert (await client.get(f"/reports/{rid}", headers=headers)).status_code == 404
