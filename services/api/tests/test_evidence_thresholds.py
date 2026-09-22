"""T030: positive, negative, boundary and conflicting cases for the evidence engine's thresholds."""

import uuid
from types import SimpleNamespace as Row
from typing import Any

import pytest
from httpx import AsyncClient
from pydantic import ValidationError

from app.config import Settings
from app.services.evidence.engine import (
    LEVEL_CEILING,
    LEVEL_RANK,
    EvidenceThresholds,
    Observations,
    ai_level,
    apply_overrides,
    build_evidence,
    synthesis_confidence,
)
from app.services.image.similarity import compare
from tests.test_evidence_engine import CLONE, ELA_ANOMALY, NOISE_ANOMALY, by_rule, forensics, rules
from tests.test_image_upload import auth_headers, make_image

T = EvidenceThresholds()


def valid_provenance() -> Any:
    return Row(
        engine="c2patool",
        engine_version="0.9",
        has_c2pa=True,
        valid_signature=True,
        signer="Cam",
        signed_at=None,
        claim_generator=None,
        normalized_json={},
    )


def png_file() -> Any:
    return Row(sha256="a" * 64, mime_type="image/png", width=1, height=1, size_bytes=1)


def software_meta(software: str) -> Any:
    return Row(
        engine="exiftool",
        engine_version="13",
        software=software,
        camera_make=None,
        camera_model=None,
        normalized_json={"has_exif": True},
    )


def two_families() -> Any:
    return forensics(ela_json=ELA_ANOMALY, noise_json=NOISE_ANOMALY)


def as_records(drafts: list[Any]) -> list[tuple[str, float | None, str]]:
    return [(d.level, d.confidence, d.kind) for d in drafts]


# -- boundaries ----------
@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (0.85, "PROBABLE"),
        (0.8499, "POSSIBLE"),
        (0.6, "POSSIBLE"),
        (0.5999, "UNKNOWN"),
        (0.0, "UNKNOWN"),
    ],
)
def test_ai_boundaries_are_inclusive_at_the_threshold(score: float, expected: str) -> None:
    assert ai_level(score, calibrated=True, t=T) == expected


def test_ai_boundaries_move_with_the_thresholds() -> None:
    t = EvidenceThresholds(ai_score_high=0.5, ai_score_medium=0.2)
    assert ai_level(0.5, calibrated=True, t=t) == "PROBABLE"
    assert ai_level(0.2, calibrated=True, t=t) == "POSSIBLE"
    assert ai_level(0.19, calibrated=True, t=t) == "UNKNOWN"


def test_phash_near_boundary_is_inclusive() -> None:
    a = Row(sha256="a" * 64, phash="0" * 16, dhash="0" * 16, ahash="0" * 16)
    # Ten differing bits on pHash exactly, dHash far apart: at the threshold counts as near.
    b = Row(sha256="b" * 64, phash="00000000000003ff", dhash="f" * 16, ahash="0" * 16)
    near = compare(a, b, near_threshold=10)
    assert near is not None and near.relation == "near"
    assert compare(a, b, near_threshold=9) is None
    same = Row(sha256="a" * 64, phash="f" * 16, dhash="f" * 16, ahash="f" * 16)
    exact = compare(a, same, near_threshold=0)
    assert exact is not None and exact.relation == "exact"


def test_language_probable_boundary() -> None:
    def text(conf: float) -> Any:
        return Row(
            word_count=1,
            sentence_count=1,
            paragraph_count=1,
            language="en",
            language_confidence=conf,
            language_json={},
            normalization_json={},
            statistics_json={},
        )

    assert (
        by_rule(build_evidence(Observations("text", text=text(0.9)), T), "text.language").level
        == "PROBABLE"
    )
    assert (
        by_rule(build_evidence(Observations("text", text=text(0.8999)), T), "text.language").level
        == "POSSIBLE"
    )
    loose = EvidenceThresholds(language_probable_confidence=0.5)
    assert (
        by_rule(build_evidence(Observations("text", text=text(0.5)), loose), "text.language").level
        == "PROBABLE"
    )


def test_forensic_family_boundary() -> None:
    one = Observations("image", forensics=forensics(ela_json=ELA_ANOMALY))
    two = Observations("image", forensics=forensics(ela_json=ELA_ANOMALY, noise_json=NOISE_ANOMALY))
    three = Observations(
        "image",
        forensics=forensics(ela_json=ELA_ANOMALY, noise_json=NOISE_ANOMALY, copy_move_json=CLONE),
    )
    for required, obs, expected in (
        (2, one, False),
        (2, two, True),
        (3, two, False),
        (3, three, True),
        (1, one, True),
    ):
        t = EvidenceThresholds(forensic_families_for_strong=required)
        assert ("forensics.multiple" in rules(build_evidence(obs, t))) is expected, (
            required,
            expected,
        )


# -- configurable confidence ----------
def test_level_default_confidence_is_configurable_but_own_numbers_are_kept() -> None:
    t = EvidenceThresholds(confidence_possible=0.3, confidence_strong=0.9, confidence_verified=0.95)
    ai = Row(provider="p", model="m", provider_version="1", score=0.7, label="x", calibrated=True)
    drafts = build_evidence(
        Observations("image", file=png_file(), metadata=software_meta("GIMP"), ai=ai), t
    )
    assert by_rule(drafts, "file.identity").confidence == 0.95
    assert by_rule(drafts, "metadata.software").confidence == 0.9
    assert by_rule(drafts, "ai.signal").confidence == pytest.approx(0.7)  # its own number
    assert (
        by_rule(
            build_evidence(Observations("image", forensics=forensics(ela_json=ELA_ANOMALY)), t),
            "forensics.ela.anomaly",
        ).confidence
        == 0.3
    )


def test_unknown_records_never_carry_confidence() -> None:
    drafts = build_evidence(Observations("image"), T)
    assert all(d.confidence is None for d in drafts if d.level == "UNKNOWN")


# -- level overrides (never stronger than the ceiling) ----------
def test_override_can_lower_a_level_and_records_it() -> None:
    t = EvidenceThresholds(level_overrides={"forensics.ela.anomaly": "UNKNOWN"})
    d = by_rule(
        build_evidence(Observations("image", forensics=forensics(ela_json=ELA_ANOMALY)), t),
        "forensics.ela.anomaly",
    )
    assert d.level == "UNKNOWN" and d.confidence is None
    assert d.data["level_override"] == {"from": "POSSIBLE", "to": "UNKNOWN"}


def test_override_cannot_raise_above_the_ceiling() -> None:
    t = EvidenceThresholds(
        level_overrides={"forensics.ela.anomaly": "VERIFIED", "metadata.software": "VERIFIED"}
    )
    obs = Observations(
        "image",
        forensics=forensics(ela_json=ELA_ANOMALY),
        metadata=software_meta("X"),
    )
    drafts = build_evidence(obs, t)
    assert by_rule(drafts, "forensics.ela.anomaly").level == "POSSIBLE"  # ceiling holds
    assert by_rule(drafts, "metadata.software").level == "STRONG"
    assert "level_override" not in by_rule(drafts, "forensics.ela.anomaly").data


def test_override_of_unknown_rule_or_invalid_level_is_ignored() -> None:
    t = EvidenceThresholds(level_overrides={"no.such.rule": "UNKNOWN", "file.identity": "BOGUS"})
    obs = Observations("image", file=png_file())
    assert build_evidence(obs, t) == build_evidence(obs, T)


def test_override_does_not_touch_conflict_records_and_every_ceiling_is_a_real_level() -> None:
    for rule, level in LEVEL_CEILING.items():
        assert level in LEVEL_RANK, rule
    t = EvidenceThresholds(level_overrides={"conflict.provenance-vs-forensics": "VERIFIED"})
    drafts = build_evidence(
        Observations("image", provenance=valid_provenance(), forensics=two_families()), t
    )
    assert by_rule(drafts, "conflict.provenance-vs-forensics").level == "UNKNOWN"
    assert apply_overrides([], t) == []


# -- synthesis confidence and conflicts ----------
def test_synthesis_confidence_is_strongest_record_minus_conflict_penalty() -> None:
    assert synthesis_confidence([], T) == 0.0
    assert synthesis_confidence([("UNKNOWN", None, "unknown")], T) == 0.0
    assert synthesis_confidence([("POSSIBLE", 0.4, "signal")], T) == 0.4
    assert synthesis_confidence([("POSSIBLE", None, "signal")], T) == 0.4  # level default
    assert synthesis_confidence([("VERIFIED", 1.0, "fact"), ("POSSIBLE", 0.4, "signal")], T) == 1.0
    with_conflict = [
        ("VERIFIED", 1.0, "fact"),
        ("STRONG", 0.8, "signal"),
        ("UNKNOWN", None, "conflict"),
    ]
    assert synthesis_confidence(with_conflict, T) == 0.75
    assert synthesis_confidence(with_conflict, EvidenceThresholds(conflict_penalty=0.5)) == 0.5
    two = [*with_conflict, ("UNKNOWN", None, "conflict")]
    assert synthesis_confidence(two, EvidenceThresholds(conflict_penalty=0.6)) == 0.0  # clipped


def test_conflict_lowers_synthesis_but_keeps_both_records_at_full_level() -> None:
    quiet = build_evidence(Observations("image", provenance=valid_provenance()), T)
    clashing = build_evidence(
        Observations("image", provenance=valid_provenance(), forensics=two_families()), T
    )
    assert synthesis_confidence(as_records(quiet), T) == 1.0
    assert synthesis_confidence(as_records(clashing), T) == 0.75
    assert by_rule(clashing, "provenance.valid").level == "VERIFIED"
    assert by_rule(clashing, "forensics.multiple").level == "STRONG"


# -- settings validation ----------
def test_settings_reject_unordered_confidence_and_invalid_overrides(tmp_path: Any) -> None:
    base = {"data_dir": tmp_path, "_env_file": None}
    with pytest.raises(ValidationError, match="ordered"):
        Settings(evidence_confidence_possible=0.9, evidence_confidence_probable=0.5, **base)
    with pytest.raises(ValidationError, match="invalid levels"):
        Settings(evidence_level_overrides={"forensics.ela.anomaly": "MAYBE"}, **base)
    ok = Settings(
        evidence_level_overrides={"forensics.ela.anomaly": "UNKNOWN"},
        evidence_conflict_penalty=0.1,
        **base,
    )
    t = EvidenceThresholds.from_settings(ok)
    assert t.level_overrides == {"forensics.ela.anomaly": "UNKNOWN"} and t.conflict_penalty == 0.1
    assert t.to_json()["confidence"]["POSSIBLE"] == 0.4


def test_settings_parse_overrides_from_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> None:
    monkeypatch.setenv("VERIXA_EVIDENCE_LEVEL_OVERRIDES", '{"matches.near": "UNKNOWN"}')
    monkeypatch.setenv("VERIXA_EVIDENCE_CONFIDENCE_POSSIBLE", "0.35")
    s = Settings(data_dir=tmp_path, _env_file=None)
    assert s.evidence_level_overrides == {"matches.near": "UNKNOWN"}
    assert s.evidence_confidence_possible == 0.35


# -- end to end: thresholds are echoed and applied ----------
async def test_api_echoes_thresholds_and_applies_overrides(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    migrated_settings.ai_detector_provider = "mock"
    migrated_settings.source_search_provider = "mock"
    migrated_settings.evidence_level_overrides = {"sources.matches": "UNKNOWN"}
    migrated_settings.evidence_confidence_verified = 0.99
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.png", make_image("PNG"), "image/png")},
    )
    aid = r.json()["id"]
    body = (await client.get(f"/analysis/{aid}/evidence", headers=headers)).json()
    assert body["thresholds"]["level_overrides"] == {"sources.matches": "UNKNOWN"}
    assert body["thresholds"]["confidence"]["VERIFIED"] == 0.99
    by = {i["rule"]: i for i in body["items"]}
    assert (
        by["sources.matches"]["level"] == "UNKNOWN" and by["sources.matches"]["confidence"] is None
    )
    assert by["file.identity"]["confidence"] == 0.99
    assert 0.0 <= body["synthesis_confidence"] <= 1.0 and body["synthesis_confidence"] == 0.99
    detail = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    step = next(s for s in detail["steps"] if s["name"] == "evidence")
    assert step["details"]["thresholds"]["conflict_penalty"] == 0.25
    assert step["details"]["synthesis_confidence"] == 0.99
    assert (
        await client.get(f"/analysis/{uuid.uuid4()}/evidence", headers=headers)
    ).status_code == 404
