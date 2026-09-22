"""T031: contradictory evidence is surfaced as conflict records and never discarded."""

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace as Row
from typing import Any

from app.services.evidence.engine import (
    EvidenceThresholds,
    Observations,
    build_evidence,
    synthesis_confidence,
)
from app.utils.timeparse import as_utc, parse_timestamp
from tests.test_evidence_engine import by_rule, rules

T = EvidenceThresholds()


def provenance(signed_at: str | None, valid: bool = True) -> Any:
    return Row(
        engine="c2patool",
        engine_version="0.9",
        has_c2pa=True,
        valid_signature=valid,
        signer="Cam",
        signed_at=signed_at,
        claim_generator=None,
        normalized_json={},
    )


def metadata(captured_raw: str, parsed: str | None, tz_known: bool) -> Any:
    return Row(
        engine="exiftool",
        engine_version="13",
        software=None,
        camera_make=None,
        camera_model=None,
        normalized_json={
            "has_exif": True,
            "captured_at": {"raw": captured_raw, "parsed": parsed, "tz_known": tz_known},
        },
    )


RUN = Row(provider="mock", provider_version="0.0")


def match(published_at: str | None) -> Any:
    return Row(url="https://x.invalid/a", published_at=published_at)


# -- timestamp parsing -----------------------------------------------------------------------------


def test_parse_timestamp_formats() -> None:
    dt, tz = parse_timestamp("2026-01-02T03:04:05Z")
    assert dt == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC) and tz
    dt, tz = parse_timestamp("2026:01:02 03:04:05+02:00")
    assert dt is not None and tz and dt.utcoffset() == timedelta(hours=2)
    dt, tz = parse_timestamp("2026:01:02 03:04:05")
    assert dt == datetime(2026, 1, 2, 3, 4, 5) and not tz
    dt, tz = parse_timestamp("2020-05-06")
    assert dt == datetime(2020, 5, 6) and not tz
    assert parse_timestamp("0000:00:00 00:00:00") == (None, False)
    assert parse_timestamp("not a date") == (None, False)
    assert parse_timestamp(None) == (None, False)
    aware = datetime(2026, 1, 1, tzinfo=timezone(timedelta(hours=-5)))
    assert as_utc(aware) == datetime(2026, 1, 1, 5, tzinfo=UTC)
    assert as_utc(datetime(2026, 1, 1)) == datetime(2026, 1, 1, tzinfo=UTC)


# -- capture after signing ----------


def test_capture_after_signing_is_a_conflict_that_keeps_both_sides() -> None:
    obs = Observations(
        "image",
        provenance=provenance("2026-01-01T10:00:00Z"),
        metadata=metadata("2026:01:01 13:00:00+00:00", "2026-01-01T13:00:00+00:00", True),
    )
    drafts = build_evidence(obs, T)
    c = by_rule(drafts, "conflict.capture-after-signing")
    assert c.kind == "conflict" and c.level == "UNKNOWN" and c.confidence is None
    assert c.conflicts_with == ["provenance.valid", "metadata.captured"]
    assert "3.0 h later" in (c.detail or "")
    assert by_rule(drafts, "provenance.valid").level == "VERIFIED"
    assert by_rule(drafts, "metadata.captured").level == "POSSIBLE"
    records = [(d.level, d.confidence, d.kind) for d in drafts]
    assert synthesis_confidence(records, T) == 0.75


def test_capture_before_or_at_signing_is_not_a_conflict() -> None:
    for captured in ("2026-01-01T09:00:00+00:00", "2026-01-01T10:00:30+00:00"):
        obs = Observations(
            "image",
            provenance=provenance("2026-01-01T10:00:00Z"),
            metadata=metadata(captured, captured, True),
        )
        assert "conflict.capture-after-signing" not in rules(build_evidence(obs, T)), captured


def test_naive_capture_time_still_compares_and_says_so() -> None:
    obs = Observations(
        "image",
        provenance=provenance("2026-01-01T10:00:00Z"),
        metadata=metadata("2026:01:02 10:00:00", "2026-01-02T10:00:00", False),
    )
    c = by_rule(build_evidence(obs, T), "conflict.capture-after-signing")
    assert "the capture time has none" in (c.limitation or "")


def test_invalid_manifest_or_unparseable_times_produce_no_time_conflict() -> None:
    obs = Observations(
        "image",
        provenance=provenance("2026-01-01T10:00:00Z", valid=False),
        metadata=metadata("2026:01:02 10:00:00", "2026-01-02T10:00:00", False),
    )
    assert "conflict.capture-after-signing" not in rules(build_evidence(obs, T))
    obs = Observations(
        "image",
        provenance=provenance("garbage"),
        metadata=metadata("2026:01:02 10:00:00", "2026-01-02T10:00:00", False),
    )
    assert "conflict.capture-after-signing" not in rules(build_evidence(obs, T))
    obs = Observations(
        "image",
        provenance=provenance("2026-01-01T10:00:00Z"),
        metadata=metadata("0000:00:00 00:00:00", None, False),
    )
    assert not [d for d in build_evidence(obs, T) if d.kind == "conflict"]


# -- published before capture ----------


def test_source_published_before_capture_is_a_conflict() -> None:
    obs = Observations(
        "image",
        metadata=metadata("2026:03:01 12:00:00+00:00", "2026-03-01T12:00:00+00:00", True),
        search_run=RUN,
        search_matches=[match(None), match("2026-02-20"), match("2026-02-01")],
    )
    drafts = build_evidence(obs, T)
    c = by_rule(drafts, "conflict.published-before-capture")
    assert c.conflicts_with == ["sources.matches", "metadata.captured"]
    assert "2026-02-01" in (c.detail or "") and "28.5 days earlier" in (c.detail or "")
    assert by_rule(drafts, "sources.matches").level == "POSSIBLE"


def test_source_published_after_capture_or_undated_is_not_a_conflict() -> None:
    later = Observations(
        "image",
        metadata=metadata("2026:03:01 12:00:00+00:00", "2026-03-01T12:00:00+00:00", True),
        search_run=RUN,
        search_matches=[match("2026-03-05")],
    )
    assert "conflict.published-before-capture" not in rules(build_evidence(later, T))
    undated = Observations(
        "image",
        metadata=metadata("2026:03:01 12:00:00+00:00", "2026-03-01T12:00:00+00:00", True),
        search_run=RUN,
        search_matches=[match(None)],
    )
    assert "conflict.published-before-capture" not in rules(build_evidence(undated, T))


def test_several_conflicts_stack_and_each_is_counted() -> None:
    obs = Observations(
        "image",
        provenance=provenance("2026-01-01T10:00:00Z"),
        metadata=metadata("2026:03:01 12:00:00+00:00", "2026-03-01T12:00:00+00:00", True),
        search_run=RUN,
        search_matches=[match("2026-02-01")],
    )
    drafts = build_evidence(obs, T)
    conflicts = [d for d in drafts if d.kind == "conflict"]
    assert {c.rule for c in conflicts} == {
        "conflict.capture-after-signing",
        "conflict.published-before-capture",
    }
    records = [(d.level, d.confidence, d.kind) for d in drafts]
    assert synthesis_confidence(records, T) == 0.5  # 1.0 - 2 x 0.25
    for c in conflicts:
        assert set(c.refs) and c.category == "synthesis" and c.source == "evidence-engine"
