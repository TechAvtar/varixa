import uuid
from types import SimpleNamespace as Row
from typing import Any

import pytest
from httpx import AsyncClient

from app.config import Settings
from app.enums import EvidenceLevel
from app.services.evidence.engine import (
    ENGINE_VERSION,
    LEVEL_CEILING,
    EvidenceThresholds,
    Observations,
    ai_level,
    build_evidence,
    summarise,
)
from tests.test_image_upload import auth_headers, image_with_mock_search_hits
from tests.test_text import ENGLISH

T = EvidenceThresholds()


def image_file() -> Any:
    return Row(sha256="a" * 64, mime_type="image/jpeg", width=10, height=20, size_bytes=300)


def rules(drafts: list[Any]) -> list[str]:
    return [d.rule for d in drafts]


def by_rule(drafts: list[Any], rule: str) -> Any:
    return next(d for d in drafts if d.rule == rule)


# -- structure ---------------------------------------------------------------------------------


def test_every_record_is_traceable_and_versioned() -> None:
    drafts = build_evidence(Observations(analysis_type="image", file=image_file()), T)
    assert drafts, "an image with nothing else still yields file + unknowns"
    for d in drafts:
        assert d.rule and d.category and d.claim and d.source
        assert d.level in {level.value for level in EvidenceLevel}
        assert d.kind in {"fact", "signal", "unknown", "conflict"}
        j = d.details_json()
        assert j["engine_version"] == ENGINE_VERSION and j["rule"] == d.rule
        assert isinstance(j["refs"], list)
    # Subsystems that did not run are reported as UNKNOWN, never silently omitted.
    assert {"provenance.uninspected", "metadata.unavailable", "forensics.unavailable"} <= set(
        rules(drafts)
    )
    assert {"ai.unavailable", "sources.unavailable"} <= set(rules(drafts))
    assert by_rule(drafts, "file.identity").level == "VERIFIED"


def test_summarise_counts_every_level() -> None:
    drafts = build_evidence(Observations(analysis_type="image", file=image_file()), T)
    counts = summarise(drafts)
    assert set(counts) == {level.value for level in EvidenceLevel}
    assert sum(counts.values()) == len(drafts) and counts["VERIFIED"] == 1


# -- initial rules table (docs/07) -----------------------------------------------------------------


def test_valid_c2pa_is_verified_and_invalid_is_possible() -> None:
    valid = Row(
        engine="c2patool",
        engine_version="0.9",
        has_c2pa=True,
        valid_signature=True,
        signer="Cam Co",
        signed_at="2026-01-01T00:00:00Z",
        claim_generator="cam/1.0",
        normalized_json={"actions": [{"action": "c2pa.created"}]},
    )
    d = by_rule(build_evidence(Observations("image", provenance=valid), T), "provenance.valid")
    assert d.level == "VERIFIED" and d.kind == "fact" and d.confidence == 1.0
    assert d.provider_version == "0.9" and d.data["signer"] == "Cam Co"

    invalid = Row(
        engine="c2patool",
        engine_version="0.9",
        has_c2pa=True,
        valid_signature=False,
        signer=None,
        signed_at=None,
        claim_generator=None,
        normalized_json={"validation_failures": [{"code": "signingCredential.untrusted"}]},
    )
    d = by_rule(build_evidence(Observations("image", provenance=invalid), T), "provenance.invalid")
    assert d.level == "POSSIBLE" and "signingCredential.untrusted" in (d.detail or "")

    absent = Row(
        engine="c2patool", engine_version="0.9", has_c2pa=False, valid_signature=None,
        signer=None, signed_at=None, claim_generator=None, normalized_json={},
    )  # fmt: skip
    d = by_rule(build_evidence(Observations("image", provenance=absent), T), "provenance.absent")
    assert d.level == "UNKNOWN" and d.kind == "unknown"


def test_exif_software_tag_is_strong_and_missing_metadata_is_unknown() -> None:
    meta = Row(
        engine="exiftool",
        engine_version="13",
        software="Adobe Photoshop 25.0",
        camera_make="Canon",
        camera_model="EOS R5",
        normalized_json={
            "has_exif": True,
            "has_xmp": False,
            "has_iptc": False,
            "gps_present": True,
            "captured_at": {"raw": "2026:01:02 03:04:05", "tz_known": False},
        },
    )
    drafts = build_evidence(Observations("image", metadata=meta), T)
    assert by_rule(drafts, "metadata.software").level == "STRONG"
    assert by_rule(drafts, "metadata.camera").level == "POSSIBLE"
    assert "timezone not recorded" in by_rule(drafts, "metadata.captured").claim
    assert by_rule(drafts, "metadata.gps").level == "POSSIBLE"
    assert "metadata.none" not in rules(drafts)

    empty = Row(
        engine="pillow", engine_version="12", software=None, camera_make=None, camera_model=None,
        normalized_json={"has_exif": False, "has_xmp": False, "has_iptc": False},
    )  # fmt: skip
    d = by_rule(build_evidence(Observations("image", metadata=empty), T), "metadata.none")
    assert d.level == "UNKNOWN" and "does not establish editing" in (d.limitation or "")


def test_exact_sha_match_is_verified_and_phash_similarity_is_possible() -> None:
    fp = Row(analysis_id=uuid.uuid4())
    other = uuid.uuid4()
    drafts = build_evidence(
        Observations(
            "image", fingerprints=fp, similar_images=[(other, "exact", 0), (other, "near", 6)]
        ),
        T,
    )
    assert by_rule(drafts, "matches.exact").level == "VERIFIED"
    near = by_rule(drafts, "matches.near")
    assert near.level == "POSSIBLE" and near.data["threshold_bits"] == T.fingerprint_near_threshold


@pytest.mark.parametrize(
    ("score", "calibrated", "expected"),
    [
        (0.95, True, "PROBABLE"),
        (0.95, False, "POSSIBLE"),  # docs/07: only a *calibrated* high signal is PROBABLE
        (0.85, True, "PROBABLE"),  # boundary is inclusive
        (0.7, True, "POSSIBLE"),
        (0.6, False, "POSSIBLE"),
        (0.59, True, "UNKNOWN"),
        (None, True, "UNKNOWN"),
    ],
)
def test_ai_levels_follow_thresholds_and_calibration(
    score: float | None, calibrated: bool, expected: str
) -> None:
    assert ai_level(score, calibrated=calibrated, t=T) == expected
    ai = Row(
        provider="p", model="m", provider_version="1", score=score, label="x", calibrated=calibrated
    )
    drafts = build_evidence(Observations("image", ai=ai), T)
    d = next(dd for dd in drafts if dd.category == "ai")
    assert d.level == expected
    if score is not None:
        assert d.confidence == pytest.approx(score)
        assert d.data["thresholds"] == {"high": T.ai_score_high, "medium": T.ai_score_medium}


def test_thresholds_are_parameters() -> None:
    strict = EvidenceThresholds(ai_score_high=0.99, ai_score_medium=0.9)
    assert ai_level(0.95, calibrated=True, t=strict) == "POSSIBLE"
    assert ai_level(0.5, calibrated=True, t=strict) == "UNKNOWN"


def test_reverse_search_match_is_possible_and_no_match_is_unknown() -> None:
    run = Row(provider="mock", provider_version="0.0")
    m = Row(url="https://x.invalid/a", published_at="2020-01-01")
    d = by_rule(
        build_evidence(Observations("image", search_run=run, search_matches=[m]), T),
        "sources.matches",
    )
    assert d.level == "POSSIBLE" and "reverse-image" in d.claim and d.data["dated"] == 1
    d = by_rule(build_evidence(Observations("image", search_run=run), T), "sources.none")
    assert d.level == "UNKNOWN"
    d = by_rule(
        build_evidence(Observations("text", search_run=run, search_matches=[m]), T),
        "sources.matches",
    )
    assert "phrase" in d.claim and "not plagiarism" in (d.limitation or "")


# -- forensics: independence ----------------------------------------------------------------------


def forensics(**kw: Any) -> Any:
    base = {
        "ela_json": {"applicable": True, "anomaly": False, "observation": "quiet", "version": "v1"},
        "compression_json": {
            "applicable": True,
            "anomaly": False,
            "prior_jpeg_grid": False,
            "encoding": {
                "progressive": False,
                "subsampling": "4:2:0",
                "standard_tables": True,
                "estimated_quality": 90,
            },
            "grid": {"offset_x": 0, "offset_y": 0},
            "format": "JPEG",
            "version": "v1",
        },
        "resampling_json": {
            "applicable": True,
            "measured": True,
            "detected": False,
            "version": "v1",
        },
        "noise_json": {
            "applicable": True,
            "measured": True,
            "blocks_smooth": 50,
            "anomaly": False,
            "version": "v1",
        },
        "copy_move_json": {
            "applicable": True,
            "measured": True,
            "detected": False,
            "version": "v1",
        },
    }
    base.update(kw)
    return Row(**base)


ELA_ANOMALY = {
    "applicable": True,
    "anomaly": True,
    "regions": [{"x": 1, "y": 2, "width": 3, "height": 4}],
    "outlier_block_fraction": 0.02,
    "version": "v1",
}
NOISE_ANOMALY = {
    "applicable": True,
    "measured": True,
    "blocks_smooth": 50,
    "anomaly": True,
    "baseline_sigma": 2.0,
    "regions": [{"x": 5, "y": 6, "width": 7, "height": 8, "sigma": 9.0}],
    "version": "v1",
}
CLONE = {
    "applicable": True,
    "measured": True,
    "detected": True,
    "matches": [
        {
            "width": 10,
            "height": 10,
            "source_x": 0,
            "source_y": 0,
            "target_x": 50,
            "target_y": 50,
            "pairs": 300,
        }
    ],
    "version": "v1",
}


def test_single_ela_anomaly_is_possible_not_strong() -> None:
    drafts = build_evidence(Observations("image", forensics=forensics(ela_json=ELA_ANOMALY)), T)
    assert by_rule(drafts, "forensics.ela.anomaly").level == "POSSIBLE"
    assert "forensics.multiple" not in rules(drafts)


def test_ela_plus_compression_grid_is_one_family_not_strong() -> None:
    comp = {**forensics().compression_json, "anomaly": True}
    drafts = build_evidence(
        Observations("image", forensics=forensics(ela_json=ELA_ANOMALY, compression_json=comp)), T
    )
    assert by_rule(drafts, "forensics.compression.offset-grid").level == "POSSIBLE"
    assert "forensics.multiple" not in rules(drafts)


def test_two_independent_families_are_strong_and_resampling_never_counts() -> None:
    res = {"applicable": True, "measured": True, "detected": True, "peaks": [], "version": "v1"}
    drafts = build_evidence(
        Observations("image", forensics=forensics(ela_json=ELA_ANOMALY, resampling_json=res)),
        T,
    )
    assert "forensics.multiple" not in rules(drafts)  # ELA + resampling is still one anomaly
    drafts = build_evidence(
        Observations("image", forensics=forensics(ela_json=ELA_ANOMALY, noise_json=NOISE_ANOMALY)),
        T,
    )
    strong = by_rule(drafts, "forensics.multiple")
    assert strong.level == "STRONG" and strong.data["families"] == [
        "error-level/compression",
        "noise",
    ]
    assert drafts.index(strong) < drafts.index(by_rule(drafts, "forensics.ela.anomaly"))
    # The requirement is a threshold, not a constant.
    three = EvidenceThresholds(forensic_families_for_strong=3)
    drafts = build_evidence(
        Observations("image", forensics=forensics(ela_json=ELA_ANOMALY, noise_json=NOISE_ANOMALY)),
        three,
    )
    assert "forensics.multiple" not in rules(drafts)
    drafts = build_evidence(
        Observations(
            "image",
            forensics=forensics(
                ela_json=ELA_ANOMALY, noise_json=NOISE_ANOMALY, copy_move_json=CLONE
            ),
        ),
        three,
    )
    assert by_rule(drafts, "forensics.multiple").data["families"] == [
        "error-level/compression",
        "noise",
        "copy-move",
    ]


def test_quiet_forensics_are_unknown_signals_never_clean() -> None:
    drafts = build_evidence(Observations("image", forensics=forensics()), T)
    for rule in (
        "forensics.ela.none",
        "forensics.compression.encoding",
        "forensics.resampling.none",
        "forensics.noise.consistent",
        "forensics.copy-move.none",
    ):
        d = by_rule(drafts, rule)
        assert d.level == "UNKNOWN", rule
    assert not any(d.level != "UNKNOWN" for d in drafts if d.category == "forensics")


# -- conflicts ------------------------------------------------------------------------------------


def test_verified_provenance_against_strong_forensics_yields_a_conflict_record() -> None:
    valid = Row(
        engine="c2patool", engine_version="0.9", has_c2pa=True, valid_signature=True,
        signer="Cam", signed_at=None, claim_generator=None, normalized_json={},
    )  # fmt: skip
    drafts = build_evidence(
        Observations(
            "image",
            provenance=valid,
            forensics=forensics(ela_json=ELA_ANOMALY, noise_json=NOISE_ANOMALY),
        ),
        T,
    )
    conflict = by_rule(drafts, "conflict.provenance-vs-forensics")
    assert conflict.kind == "conflict" and conflict.level == "UNKNOWN"
    assert conflict.conflicts_with == ["provenance.valid", "forensics.multiple"]
    # Both sides are retained, unchanged.
    assert by_rule(drafts, "provenance.valid").level == "VERIFIED"
    assert by_rule(drafts, "forensics.multiple").level == "STRONG"
    assert set(conflict.refs) >= set(by_rule(drafts, "provenance.valid").refs)


def test_no_conflict_without_a_verified_side_or_a_strong_signal() -> None:
    drafts = build_evidence(
        Observations("image", forensics=forensics(ela_json=ELA_ANOMALY, noise_json=NOISE_ANOMALY)),
        T,
    )
    assert not [d for d in drafts if d.kind == "conflict"]


# -- text -----------------------------------------------------------------------------------------


def test_text_rules() -> None:
    tx = Row(
        word_count=1200,
        sentence_count=60,
        paragraph_count=5,
        language="en",
        language_confidence=0.97,
        language_json={"engine": "langdetect"},
        normalization_json={"zero_width_removed": 2, "bidi_controls_removed": 0},
        statistics_json={"repeated_sentence_count": 1},
    )
    drafts = build_evidence(Observations("text", text=tx), T)
    assert by_rule(drafts, "text.stats").level == "VERIFIED"
    assert by_rule(drafts, "text.language").level == "PROBABLE"
    assert by_rule(drafts, "text.hidden").data["hidden_characters"] == 2
    assert by_rule(drafts, "text.repetition").level == "POSSIBLE"
    tx.language_confidence = 0.5
    assert (
        by_rule(build_evidence(Observations("text", text=tx), T), "text.language").level
        == "POSSIBLE"
    )


# -- pipeline + API -------------------------------------------------------------------------------


@pytest.fixture
def mock_providers(migrated_settings: Settings) -> Settings:
    migrated_settings.ai_detector_provider = "mock"
    migrated_settings.source_search_provider = "mock"
    return migrated_settings


async def test_image_pipeline_persists_evidence_and_api_serves_it(
    client: AsyncClient, mock_providers: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.jpg", image_with_mock_search_hits("JPEG"), "image/jpeg")},
    )
    aid = r.json()["id"]
    detail = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    step = next(s for s in detail["steps"] if s["name"] == "evidence")
    assert step["status"] == "completed" and step["details"]["records"] > 5
    body = (await client.get(f"/analysis/{aid}/evidence", headers=headers)).json()
    assert body["engine_version"] == ENGINE_VERSION and body["generated_at"]
    assert sum(body["counts"].values()) == len(body["items"]) == step["details"]["records"]
    by = {i["rule"]: i for i in body["items"]}
    assert by["file.identity"]["level"] == "VERIFIED" and by["file.identity"]["kind"] == "fact"
    assert "row:analysis_files" in by["file.identity"]["refs"]
    # Mock AI + mock search show up with provider-call references.
    ai = next(i for i in body["items"] if i["category"] == "ai")
    assert any(ref.startswith("provider_call:") for ref in ai["refs"])
    assert ai["provider_version"] and ai["confidence"] is not None
    assert by["sources.matches"]["level"] == "POSSIBLE"
    assert all(i["limitation"] for i in body["items"] if i["level"] == "POSSIBLE")


async def test_text_pipeline_persists_evidence(
    client: AsyncClient, mock_providers: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})
    aid = r.json()["id"]
    body = (await client.get(f"/analysis/{aid}/evidence", headers=headers)).json()
    rules_ = {i["rule"] for i in body["items"]}
    assert {"file.identity", "text.stats", "text.language"} <= rules_
    assert not any(i["category"] in {"metadata", "provenance", "forensics"} for i in body["items"])


async def test_evidence_endpoint_enforces_ownership_and_404s(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    owner = await auth_headers(client, "o@example.com")
    r = await client.post("/analysis/text", headers=owner, json={"text": ENGLISH})
    aid = r.json()["id"]
    intruder = await auth_headers(client, "i@example.com")
    assert (await client.get(f"/analysis/{aid}/evidence", headers=intruder)).status_code == 404
    assert (
        await client.get(f"/analysis/{uuid.uuid4()}/evidence", headers=owner)
    ).status_code == 404
    assert (await client.get(f"/analysis/{aid}/evidence")).status_code == 401


async def test_rerun_replaces_rather_than_duplicates(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    from app.services.analysis.evidence_step import EvidenceStep
    from app.services.analysis.pipeline import PipelineContext

    headers = await auth_headers(client)
    r = await client.post("/analysis/text", headers=headers, json={"text": ENGLISH})
    aid = r.json()["id"]
    first = (await client.get(f"/analysis/{aid}/evidence", headers=headers)).json()
    app = client._transport.app  # type: ignore[attr-defined]
    async with app.state.session_factory() as db:
        from app.repositories.analysis import AnalysisRepository

        analysis = await AnalysisRepository(db).get(uuid.UUID(aid))
        assert analysis is not None
        ctx = PipelineContext(
            analysis=analysis,
            file=analysis.files[0],
            session=db,
            storage=app.state.storage,
            settings=migrated_settings,
        )
        await EvidenceStep().run(ctx)
        await db.commit()
    second = (await client.get(f"/analysis/{aid}/evidence", headers=headers)).json()
    assert len(second["items"]) == len(first["items"])
    assert {i["rule"] for i in second["items"]} == {i["rule"] for i in first["items"]}


# -- T045: signed declarations, ingredients, manifest chain ----------------------------------


def provenance_row(**normalized: Any) -> Any:
    base: dict[str, Any] = {
        "actions": [],
        "assertions": {},
        "software_agents": [],
        "ingredients": [],
        "ingredient_failures": 0,
        "manifest_chain": [],
        "manifest_order_conflict": False,
        "validation_codes": ["claimSignature.validated"],
    }
    base.update(normalized)
    return Row(
        engine="c2patool",
        engine_version="0.9",
        has_c2pa=True,
        valid_signature=True,
        signer="Cam Co",
        signed_at="2026-01-01T00:00:00Z",
        claim_generator="cam/1.0",
        ingredient_count=len(base["ingredients"]),
        normalized_json=base,
    )


def test_signed_source_type_is_strong_when_algorithmic_and_intact() -> None:
    row = provenance_row(
        assertions={
            "source_types": [
                {
                    "action": "c2pa.created",
                    "uri": "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia",
                    "short": "trainedAlgorithmicMedia",
                }
            ]
        }
    )
    drafts = build_evidence(Observations("image", provenance=row), T)
    d = by_rule(drafts, "provenance.source-type")
    assert d.level == "STRONG" and d.kind == "signal" and d.data["algorithmic"] is True
    assert "verified as stated" in (d.limitation or "")
    assert "hash_coverage" not in by_rule(drafts, "provenance.valid").data


def test_signed_capture_source_type_is_possible() -> None:
    row = provenance_row(
        assertions={
            "source_types": [{"action": "c2pa.created", "uri": "x", "short": "digitalCapture"}]
        }
    )
    d = by_rule(build_evidence(Observations("image", provenance=row), T), "provenance.source-type")
    assert d.level == "POSSIBLE" and d.data["algorithmic"] is False


def test_declarations_drop_to_possible_when_signature_invalid() -> None:
    row = Row(
        engine="c2patool",
        engine_version="0.9",
        has_c2pa=True,
        valid_signature=False,
        signer=None,
        signed_at=None,
        claim_generator=None,
        ingredient_count=0,
        normalized_json={
            "validation_failures": [{"code": "assertion.dataHash.mismatch"}],
            "assertions": {
                "training_mining": {"c2pa.ai_generative_training": "notAllowed"},
                "source_types": [{"action": None, "uri": "x", "short": "trainedAlgorithmicMedia"}],
            },
        },
    )
    drafts = build_evidence(Observations("image", provenance=row), T)
    assert by_rule(drafts, "provenance.invalid").level == "POSSIBLE"
    assert by_rule(drafts, "provenance.training-mining").level == "POSSIBLE"
    assert by_rule(drafts, "provenance.source-type").level == "POSSIBLE"
    assert "did not validate" in (by_rule(drafts, "provenance.source-type").limitation or "")


def test_training_mining_identity_and_ingredient_rules() -> None:
    row = provenance_row(
        assertions={
            "training_mining": {"c2pa.ai_generative_training": "notAllowed"},
            "identity": {
                "present": True,
                "kind": "cawg.identity_claims_aggregation",
                "names": ["Ada"],
            },
        },
        ingredients=[
            {"title": "a", "failure_codes": ["assertion.dataHash.mismatch"], "children": []}
        ],
        ingredient_failures=1,
        validation_codes=["claimSignature.validated", "cawg.ica.credential_valid"],
    )
    drafts = build_evidence(Observations("image", provenance=row), T)
    tm = by_rule(drafts, "provenance.training-mining")
    assert tm.level == "STRONG" and "notAllowed" in (tm.detail or "")
    ident = by_rule(drafts, "provenance.identity")
    assert ident.level == "STRONG" and ident.data["validated"] is True and ident.detail == "Ada"
    ing = by_rule(drafts, "provenance.ingredient.invalid")
    assert ing.level == "POSSIBLE" and ing.data["ingredient_failures"] == 1


def test_unvalidated_identity_is_possible() -> None:
    row = provenance_row(
        assertions={"identity": {"present": True, "kind": None, "names": []}},
        validation_codes=["claimSignature.validated", "cawg.ica.untrusted_issuer"],
    )
    d = by_rule(build_evidence(Observations("image", provenance=row), T), "provenance.identity")
    assert d.level == "POSSIBLE" and d.data["validated"] is False


def test_hash_coverage_and_agents_enrich_the_valid_record() -> None:
    row = provenance_row(
        assertions={"hash_data": {"alg": "sha256", "exclusion_count": 1, "exclusions": []}},
        software_agents=[{"name": "Editor", "version": "2.0", "origin": "action"}],
    )
    d = by_rule(build_evidence(Observations("image", provenance=row), T), "provenance.valid")
    assert d.data["hash_coverage"] == {"algorithm": "sha256", "excluded_ranges": 1}
    assert d.data["software_agents"][0]["name"] == "Editor"
    assert "covers the file bytes" in (d.detail or "")


def test_new_provenance_rules_have_ceilings() -> None:
    for rule in (
        "provenance.source-type",
        "provenance.training-mining",
        "provenance.identity",
        "provenance.ingredient.invalid",
    ):
        assert rule in LEVEL_CEILING and LEVEL_CEILING[rule] in {"STRONG", "POSSIBLE"}
