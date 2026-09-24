import uuid
from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient

from app.providers.provenance import (
    C2paToolInspector,
    NullProvenanceInspector,
    ProvenanceInspectionError,
    build_provenance_inspector,
    find_c2patool,
)
from app.providers.provenance.base import RawProvenance
from app.providers.provenance.c2patool import (
    C2paToolCapabilities,
    _TransientError,
    parse_help,
)
from app.services.image.provenance import (
    NormalizedProvenance,
    classify_code,
    normalize_provenance,
    provenance_limitations,
)
from tests.test_image_upload import auth_headers, make_image

FIXTURES = Path(__file__).parent / "fixtures" / "c2pa"
SIGNED = (FIXTURES / "signed_sample.jpg").read_bytes()

C2PATOOL = find_c2patool()
needs_c2patool = pytest.mark.skipif(C2PATOOL is None, reason="c2patool not installed")


def raw_signed(*, failures: bool = False) -> RawProvenance:
    status = [
        {"code": "claimSignature.validated", "explanation": "claim signature valid"},
        {"code": "assertion.dataHash.match", "explanation": "data hash valid"},
    ]
    if failures:
        status.append({"code": "assertion.dataHash.mismatch", "explanation": "data hash changed"})
    return RawProvenance(
        engine="c2patool",
        engine_version="0.9.12",
        present=True,
        summary={
            "active_manifest": "urn:a",
            "manifests": {
                "urn:a": {
                    "claim_generator": "make_test_images/0.12.0 c2pa-rs/0.12.0",
                    "title": "C.jpg",
                    "ingredients": [{"title": "parent"}],
                    "assertions": [
                        {
                            "label": "stds.schema-org.CreativeWork",
                            "data": {"author": [{"@type": "Person", "name": "Gavin Peacock"}]},
                        },
                        {
                            "label": "c2pa.actions",
                            "data": {
                                "actions": [
                                    {"action": "c2pa.created"},
                                    {"action": "c2pa.drawing", "parameters": {"name": "gradient"}},
                                ]
                            },
                        },
                    ],
                    "signature_info": {
                        "alg": "Ps256",
                        "issuer": "C2PA Test Signing Cert",
                        "time": "2022-08-19T19:03:41+00:00",
                    },
                }
            },
        },
        detailed={"validation_status": status},
        validation_status=status,
    )


# -- normalisation ----------------------------------------------------------------------


def test_normalize_absent_manifest_is_unknown_not_invalid() -> None:
    n = normalize_provenance(RawProvenance(engine="c2patool", engine_version="0.9", present=False))
    assert n.has_c2pa is False and n.valid_signature is None and n.signer is None
    notes = provenance_limitations(n)
    assert any("does not establish" in x for x in notes)


def test_normalize_signed_manifest() -> None:
    n = normalize_provenance(raw_signed())
    assert n.has_c2pa and n.valid_signature is True
    assert n.signer == "C2PA Test Signing Cert" and n.signature_alg == "Ps256"
    assert n.signed_at == "2022-08-19T19:03:41+00:00"
    assert n.claim_generator.startswith("make_test_images")  # type: ignore[union-attr]
    assert n.title == "C.jpg" and n.manifest_count == 1 and n.ingredient_count == 1
    assert n.assertion_labels == ["stds.schema-org.CreativeWork", "c2pa.actions"]
    assert [a["action"] for a in n.actions] == ["c2pa.created", "c2pa.drawing"]
    assert n.actions[1]["parameters"] == {"name": "gradient"}
    assert n.authors == ["Gavin Peacock"]
    assert n.validation_failures == []
    notes = provenance_limitations(n)
    assert any("does not prove the claims are true" in x for x in notes)
    assert any("trust" in x.lower() for x in notes)


def test_normalize_flags_validation_failures() -> None:
    n = normalize_provenance(raw_signed(failures=True))
    assert n.valid_signature is False
    assert n.validation_failures[0]["code"] == "assertion.dataHash.mismatch"
    assert any("reported problems" in x for x in provenance_limitations(n))


def test_normalize_survives_malformed_summary() -> None:
    raw = RawProvenance(
        engine="c2patool",
        engine_version="0.9",
        present=True,
        summary={"active_manifest": "x", "manifests": {"x": {"assertions": ["junk", 5]}}},
    )
    n = normalize_provenance(raw)
    assert n.has_c2pa and n.valid_signature is False and n.assertion_labels == []


# -- adapter --------------------------------------------------------------------------------


@needs_c2patool
async def test_c2patool_reads_signed_sample(tmp_path: Path) -> None:
    assert C2PATOOL is not None
    inspector = C2paToolInspector(C2PATOOL, temp_dir=tmp_path / "tmp")
    raw = await inspector.inspect(SIGNED, extension="jpg")
    assert raw.present and raw.engine_version.startswith("0.")
    n = normalize_provenance(raw)
    assert n.valid_signature is True and n.signer == "C2PA Test Signing Cert"
    assert "claimSignature.validated" in n.validation_codes
    assert not list((tmp_path / "tmp").glob("*"))  # temp file removed


@needs_c2patool
async def test_c2patool_reports_absence_for_plain_image(tmp_path: Path) -> None:
    assert C2PATOOL is not None
    raw = await C2paToolInspector(C2PATOOL, temp_dir=tmp_path).inspect(
        make_image("JPEG"), extension="jpg"
    )
    assert raw.present is False and raw.summary is None


@needs_c2patool
async def test_c2patool_never_trusts_the_extension(tmp_path: Path) -> None:
    """An unexpected extension is replaced by .bin (never used as a path), and the
    resulting c2patool error surfaces as an inspection error, not a crash."""
    assert C2PATOOL is not None
    inspector = C2paToolInspector(C2PATOOL, temp_dir=tmp_path / "t")
    hostile = "../.." + chr(92) + "png; rm -rf"
    with pytest.raises(ProvenanceInspectionError, match="could not read"):
        await inspector.inspect(make_image("PNG"), extension=hostile)
    assert not list((tmp_path / "t").glob("*")) and not list(tmp_path.glob("*.png"))


async def test_null_inspector_raises() -> None:
    with pytest.raises(ProvenanceInspectionError):
        await NullProvenanceInspector().inspect(b"x", extension="jpg")


def test_build_inspector_respects_setting(migrated_settings: Any) -> None:
    migrated_settings.provenance_engine = "none"
    assert build_provenance_inspector(migrated_settings).name == "none"
    if C2PATOOL:
        migrated_settings.provenance_engine = "auto"
        assert build_provenance_inspector(migrated_settings).name == "c2patool"


# -- step + API -------------------------------------------------------------------------------


@needs_c2patool
async def test_signed_upload_persists_provenance(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image", headers=headers, files={"file": ("C.jpg", SIGNED, "image/jpeg")}
    )
    assert r.status_code == 201, r.text
    analysis_id = r.json()["id"]
    detail = (await client.get(f"/analysis/{analysis_id}", headers=headers)).json()
    step = next(s for s in detail["steps"] if s["name"] == "provenance")
    assert step["status"] == "completed" and step["details"]["has_c2pa"] is True

    body = (await client.get(f"/analysis/{analysis_id}/provenance", headers=headers)).json()
    n = body["normalized"]
    assert n["has_c2pa"] and n["valid_signature"] is True
    assert n["signer"] == "C2PA Test Signing Cert" and n["authors"] == ["Gavin Peacock"]
    assert body["manifests"] and body["validation_status"]
    assert any("does not prove" in x for x in body["limitations"])


async def test_unsigned_upload_reports_unknown(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("p.png", make_image("PNG"), "image/png")},
    )
    analysis_id = r.json()["id"]
    r = await client.get(f"/analysis/{analysis_id}/provenance", headers=headers)
    if C2PATOOL is None:
        # No engine: the step fails softly and there is nothing to return.
        assert r.status_code == 404
        detail = (await client.get(f"/analysis/{analysis_id}", headers=headers)).json()
        assert detail["status"] == "completed"  # non-critical step never sinks the analysis
        return
    body = r.json()
    assert body["normalized"]["has_c2pa"] is False and body["normalized"]["valid_signature"] is None
    assert any("does not establish" in x for x in body["limitations"])


async def test_provenance_endpoint_enforces_ownership(client: AsyncClient) -> None:
    owner = await auth_headers(client, "owner@example.com")
    r = await client.post(
        "/analysis/image", headers=owner, files={"file": ("a.png", make_image("PNG"), "image/png")}
    )
    intruder = await auth_headers(client, "intruder@example.com")
    aid = r.json()["id"]
    assert (await client.get(f"/analysis/{aid}/provenance", headers=intruder)).status_code == 404
    assert (
        await client.get(f"/analysis/{uuid.uuid4()}/provenance", headers=owner)
    ).status_code == 404
    assert (await client.get(f"/analysis/{aid}/provenance")).status_code == 401


# -- Phase 1: capability probe, retries, code families, structured validation ----------------

HELP_0_9_12 = """Usage: c2patool [OPTIONS] <PATH> [COMMAND]

Commands:
  trust     Sub-command to configure trust store options
  fragment  Sub-command to add or verify fragmented BMFF
  help      Print this message

Options:
  -m, --manifest <MANIFEST>  Path to manifest definition JSON file
  -d, --detailed             Display detailed C2PA-formatted manifest data
  -i, --ingredient           Write ingredient report and assets to a folder
      --tree                 Create a tree diagram of the manifest store
      --certs                Extract certificate chain
      --info                 Show manifest size, source and validation info
  -h, --help                 Print help
  -V, --version              Print version
"""


def test_parse_help_reads_flags_and_subcommands() -> None:
    caps = parse_help("c2patool 0.9.12", HELP_0_9_12)
    assert caps.version == "0.9.12" and caps.version_tuple == (0, 9, 12)
    assert caps.has_flag("--info") and caps.has_flag("--certs") and caps.has_flag("--tree")
    assert not caps.has_flag("--external-manifest") and not caps.has_flag("--settings")
    assert caps.has_trust_subcommand and "fragment" in caps.subcommands
    assert "help" not in caps.subcommands
    assert caps.to_json()["flags"] == sorted(caps.flags)


def test_parse_help_tolerates_unknown_output() -> None:
    caps = parse_help("", "garbage")
    assert caps.version == "unknown" and caps.flags == frozenset()
    assert not caps.has_trust_subcommand


async def test_run_retries_once_only_for_transient_failures(tmp_path: Path) -> None:
    inspector = C2paToolInspector("c2patool-not-real", temp_dir=tmp_path)
    calls: list[int] = []

    async def flaky(args: list[str]) -> tuple[bytes, bytes, int]:
        calls.append(1)
        if len(calls) == 1:
            raise _TransientError("could not be started")
        return b"c2patool 9.9.9", b"", 0

    inspector._run_once = flaky  # type: ignore[method-assign]
    out, _, _ = await inspector._run(["--version"])
    assert out == b"c2patool 9.9.9" and len(calls) == 2

    async def always(args: list[str]) -> tuple[bytes, bytes, int]:
        calls.append(1)
        raise _TransientError("killed")

    calls.clear()
    inspector._run_once = always  # type: ignore[method-assign]
    with pytest.raises(ProvenanceInspectionError, match="killed"):
        await inspector._run(["--version"])
    assert len(calls) == 2  # exactly one retry

    async def timeout(args: list[str]) -> tuple[bytes, bytes, int]:
        calls.append(1)
        raise ProvenanceInspectionError("c2patool timed out")

    calls.clear()
    inspector._run_once = timeout  # type: ignore[method-assign]
    with pytest.raises(ProvenanceInspectionError, match="timed out"):
        await inspector._run(["--version"])
    assert len(calls) == 1  # timeouts are never retried


@pytest.mark.parametrize(
    ("code", "explanation", "family"),
    [
        ("claimSignature.validated", None, "info"),
        ("assertion.dataHash.match", None, "info"),
        ("assertion.dataHash.mismatch", None, "integrity"),
        ("claimSignature.mismatch", None, "integrity"),
        ("signingCredential.untrusted", "signing certificate untrusted", "trust"),
        ("signingCredential.expired", None, "trust"),
        ("timeStamp.untrusted", None, "trust"),
        ("general.error", "claim signature is not valid: CoseCertUntrusted", "trust"),
        ("general.error", "claim signature is not valid: CoseSignature", "integrity"),
        ("cawg.ica.untrusted_issuer", None, "identity"),
        ("cawg.ica.credential_valid", None, "identity"),
        ("something.new.notFound", None, "integrity"),
        ("something.new.note", None, "info"),
    ],
)
def test_classify_code(code: str, explanation: str | None, family: str) -> None:
    assert classify_code(code, explanation) == family


def _raw(summary: Any, **kwargs: Any) -> RawProvenance:
    return RawProvenance(
        engine="c2patool", engine_version="0.9.12", present=True, summary=summary, **kwargs
    )


def test_untrusted_signer_does_not_read_as_altered_manifest() -> None:
    """c2patool with a trust list reports untrusted + general.error for an intact manifest."""
    raw = raw_signed()
    status = [
        *raw.validation_status,
        {"code": "signingCredential.untrusted", "explanation": "signing certificate untrusted"},
        {"code": "general.error", "explanation": "claim signature is not valid: CoseCertUntrusted"},
    ]
    n = normalize_provenance(
        _raw(raw.summary, detailed={"validation_status": status}, validation_status=status)
    )
    assert n.valid_signature is True and n.validation_failures == []
    assert "signingCredential.untrusted" in n.validation["active_manifest"]["informational"]


def test_structured_validation_from_flat_status() -> None:
    n = normalize_provenance(raw_signed(failures=True))
    v = n.validation
    assert v["source"] == "validation_status" and v["state"] is None
    assert v["active_manifest"]["success"] == [
        "claimSignature.validated",
        "assertion.dataHash.match",
    ]
    assert v["active_manifest"]["failure"] == ["assertion.dataHash.mismatch"]
    assert v["ingredients"] == {}


def test_structured_validation_from_validation_results() -> None:
    """Newer engines (c2pa-rs >= 0.4x) report validation_results and a validation_state."""
    raw = raw_signed()
    results: dict[str, Any] = {
        "activeManifest": {
            "success": [{"code": "claimSignature.validated", "url": "x", "explanation": "ok"}],
            "informational": [{"code": "signingCredential.untrusted", "url": "x"}],
            "failure": [],
        },
        "ingredientDeltas": [
            {
                "ingredientAssertionURI": "self#jumbf=c2pa.assertions/c2pa.ingredient",
                "validationDeltas": {
                    "success": [],
                    "informational": [],
                    "failure": [{"code": "assertion.dataHash.mismatch", "url": "y"}],
                },
            }
        ],
    }
    n = normalize_provenance(
        _raw(
            raw.summary,
            detailed={"validation_results": results, "validation_state": "Valid"},
            validation_results=results,
            validation_state="Valid",
        )
    )
    assert n.valid_signature is True  # signature validated, no active-manifest failure
    assert n.validation["state"] == "Valid" and n.validation["source"] == "validation_results"
    assert n.validation["active_manifest"]["informational"] == ["signingCredential.untrusted"]
    key = "self#jumbf=c2pa.assertions/c2pa.ingredient"
    assert n.validation["ingredients"][key]["failure"] == ["assertion.dataHash.mismatch"]

    results["activeManifest"]["failure"] = [{"code": "assertion.dataHash.mismatch"}]
    n = normalize_provenance(
        _raw(raw.summary, detailed={}, validation_results=results, validation_state="Invalid")
    )
    assert n.valid_signature is False
    assert n.validation_failures == [{"code": "assertion.dataHash.mismatch", "explanation": None}]


def test_info_report_is_parsed() -> None:
    raw = raw_signed()
    info = (
        "Information for x.jpg\nManifest store size = 51167 (36.46% of file size 140346)\n"
        "Validated\nOne manifest"
    )
    n = normalize_provenance(
        _raw(
            raw.summary,
            detailed=raw.detailed,
            validation_status=raw.validation_status,
            info=info,
        )
    )
    assert n.info == {"manifest_store_bytes": 51167, "manifest_count": 1, "validated": True}


def test_recorded_0_9_12_output_normalises() -> None:
    import json

    summary = json.loads((FIXTURES / "json" / "summary_0.9.12.json").read_text("utf-8"))
    detailed = json.loads((FIXTURES / "json" / "detailed_0.9.12.json").read_text("utf-8"))
    n = normalize_provenance(
        _raw(summary, detailed=detailed, validation_status=detailed["validation_status"])
    )
    assert n.valid_signature is True and n.signer == "C2PA Test Signing Cert"
    assert n.validation["active_manifest"]["failure"] == []
    assert "c2pa.actions" in n.assertion_labels


def test_pre_upgrade_row_still_loads() -> None:
    """Rows written before Phase 1 lack the new keys; the route rebuilds them with defaults."""
    old_row: dict[str, Any] = {
        "engine": "c2patool",
        "engine_version": "0.9.12",
        "has_c2pa": True,
        "valid_signature": True,
        "signer": "X",
        "signature_alg": "Ps256",
        "signed_at": None,
        "claim_generator": None,
        "title": None,
        "active_manifest": None,
        "manifest_count": 1,
        "ingredient_count": 0,
        "assertion_labels": [],
        "actions": [],
        "authors": [],
        "validation_codes": [],
        "validation_failures": [],
        "warnings": [],
    }
    n = NormalizedProvenance(**old_row)
    assert n.validation == {} and n.info == {}
    assert provenance_limitations(n)


def test_capabilities_value_object() -> None:
    caps = C2paToolCapabilities(
        version="1.0.0", flags=frozenset({"--info"}), subcommands=frozenset()
    )
    assert caps.has_flag("--info") and caps.version_tuple == (1, 0, 0)
