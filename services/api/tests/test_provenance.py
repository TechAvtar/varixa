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
    SETTINGS_FILE,
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
    """An unexpected extension is replaced by .bin (never used as a path). Older engines
    refuse the unknown extension (an inspection error, not a crash); 0.28 sniffs the bytes
    and reports no claim. Either way nothing is written outside the temp dir."""
    assert C2PATOOL is not None
    inspector = C2paToolInspector(C2PATOOL, temp_dir=tmp_path / "t")
    hostile = "../.." + chr(92) + "png; rm -rf"
    try:
        raw = await inspector.inspect(make_image("PNG"), extension=hostile)
    except ProvenanceInspectionError as exc:
        assert "could not read" in str(exc)
    else:
        assert raw.present is False
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
    assert "signingCredential.untrusted" in n.validation["active_manifest"]["trust"]


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
    assert n.validation["active_manifest"]["trust"] == ["signingCredential.untrusted"]
    assert n.validation["active_manifest"]["informational"] == []
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


# -- Phase 2: assertion depth, ingredient tree, manifest chain ------------------------------

SOURCE_AI = "http://cv.iptc.org/newscodes/digitalsourcetype/trainedAlgorithmicMedia"


def composite_summary() -> dict[str, Any]:
    """An edit (urn:b) whose parent ingredient (urn:a) was itself signed, plus a second
    ingredient whose recorded validation failed. urn:a was signed *after* urn:b."""
    return {
        "active_manifest": "urn:b",
        "manifests": {
            "urn:b": {
                "claim_generator": "editor/2.0",
                "title": "edit.jpg",
                "claim_generator_info": [{"name": "Editor", "version": "2.0"}],
                "ingredients": [
                    {
                        "title": "parent.jpg",
                        "format": "image/jpeg",
                        "relationship": "parentOf",
                        "document_id": "xmp:did:1",
                        "instance_id": "xmp:iid:1",
                        "active_manifest": "urn:a",
                        "thumbnail": {"format": "image/jpeg", "identifier": "self#jumbf=x"},
                        "validation_status": [{"code": "claimSignature.validated"}],
                    },
                    {
                        "title": "sticker.png",
                        "format": "image/png",
                        "relationship": "componentOf",
                        "validation_status": [{"code": "assertion.dataHash.mismatch"}],
                    },
                ],
                "assertions": [
                    {
                        "label": "c2pa.actions.v2",
                        "data": {
                            "actions": [
                                {
                                    "action": "c2pa.opened",
                                    "softwareAgent": {"name": "Editor", "version": "2.0"},
                                },
                                {
                                    "action": "c2pa.edited",
                                    "digitalSourceType": SOURCE_AI,
                                    "softwareAgent": "Plugin 1.1",
                                },
                            ]
                        },
                    },
                    {
                        "label": "c2pa.training-mining",
                        "data": {
                            "entries": {
                                "c2pa.ai_generative_training": {"use": "notAllowed"},
                                "c2pa.data_mining": {"use": "allowed"},
                            }
                        },
                    },
                    {
                        "label": "cawg.identity",
                        "data": {
                            "signer_payload": {"referenced_assertions": [{"url": "x"}]},
                            "signature_type": "cawg.identity_claims_aggregation",
                            "verifiedIdentities": [{"type": "cawg.social_media", "name": "Ada"}],
                        },
                    },
                ],
                "signature_info": {
                    "alg": "Ps256",
                    "issuer": "Editor Inc",
                    "time": "2026-01-02T00:00:00+00:00",
                },
            },
            "urn:a": {
                "claim_generator": "camera/1.0",
                "title": "parent.jpg",
                "ingredients": [],
                "assertions": [
                    {
                        "label": "c2pa.actions",
                        "data": {
                            "actions": [
                                {
                                    "action": "c2pa.created",
                                    "digitalSourceType": "http://cv.iptc.org/newscodes/"
                                    "digitalsourcetype/digitalCapture",
                                }
                            ]
                        },
                    }
                ],
                "signature_info": {
                    "alg": "Es256",
                    "issuer": "Cam Co",
                    "time": "2026-01-03T00:00:00+00:00",
                },
            },
        },
    }


def composite_detailed() -> dict[str, Any]:
    return {
        "active_manifest": "urn:b",
        "manifests": {
            "urn:b": {
                "assertion_store": {
                    "c2pa.hash.data": {
                        "exclusions": [{"start": 20, "length": 51179}],
                        "name": "jumbf manifest",
                        "alg": "sha256",
                    }
                }
            }
        },
        "validation_status": [
            {"code": "claimSignature.validated", "explanation": "ok"},
            {"code": "cawg.ica.credential_valid", "explanation": "identity ok"},
        ],
    }


def composite_raw() -> RawProvenance:
    d = composite_detailed()
    return RawProvenance(
        engine="c2patool",
        engine_version="0.9.12",
        present=True,
        summary=composite_summary(),
        detailed=d,
        validation_status=d["validation_status"],
        tree="Tree View:\n Asset:edit.jpg, Manifest:urn:b\n",
    )


def test_depth_reads_signed_declarations() -> None:
    n = normalize_provenance(composite_raw())
    a = n.assertions
    assert a["hash_data"]["alg"] == "sha256" and a["hash_data"]["exclusion_count"] == 1
    assert a["source_types"] == [
        {"action": "c2pa.edited", "uri": SOURCE_AI, "short": "trainedAlgorithmicMedia"}
    ]
    assert a["training_mining"] == {
        "c2pa.ai_generative_training": "notAllowed",
        "c2pa.data_mining": "allowed",
    }
    assert a["identity"]["present"] and a["identity"]["names"] == ["Ada"]
    assert a["identity"]["kind"] == "cawg.identity_claims_aggregation"
    names = {(x["name"], x["version"], x["origin"]) for x in n.software_agents}
    assert ("Editor", "2.0", "action") in names and ("Plugin 1.1", None, "action") in names


def test_depth_reads_ingredient_tree_and_failures() -> None:
    n = normalize_provenance(composite_raw())
    assert n.ingredient_count == 2 and len(n.ingredients) == 2
    parent, sticker = n.ingredients
    assert parent["title"] == "parent.jpg" and parent["relationship"] == "parentOf"
    assert parent["manifest_label"] == "urn:a" and parent["failure_codes"] == []
    assert parent["children"] == []  # urn:a has no ingredients of its own
    assert sticker["failure_codes"] == ["assertion.dataHash.mismatch"]
    assert n.ingredient_failures == 1
    assert any("ingredients carry validation failures" in x for x in provenance_limitations(n))


def test_depth_reads_manifest_chain_and_order_conflict() -> None:
    n = normalize_provenance(composite_raw())
    labels = [m["label"] for m in n.manifest_chain]
    assert labels == ["urn:b", "urn:a"]
    assert n.manifest_chain[1]["parent"] == "urn:b"
    assert n.manifest_order_conflict is True  # parent signed a day after the derived manifest
    assert n.manifest_chain[1]["signed_after_parent"] is True


def test_depth_ignores_cycles_and_caps_nodes() -> None:
    summary = composite_summary()
    summary["manifests"]["urn:a"]["ingredients"] = [{"title": "loop", "active_manifest": "urn:b"}]
    n = normalize_provenance(
        RawProvenance(engine="c2patool", engine_version="0.9.12", present=True, summary=summary)
    )
    assert [m["label"] for m in n.manifest_chain] == ["urn:b", "urn:a"]
    assert n.ingredients[0]["children"][0]["title"] == "loop"


def test_depth_is_empty_for_a_plain_signed_manifest() -> None:
    n = normalize_provenance(raw_signed())
    assert n.assertions == {} and n.software_agents == []
    # raw_signed() lists one ingredient without a manifest of its own: a leaf node, no failures.
    assert [i["title"] for i in n.ingredients] == ["parent"] and n.ingredient_failures == 0
    assert n.manifest_chain[0]["label"] == "urn:a" and not n.manifest_order_conflict


@needs_c2patool
async def test_c2patool_tree_is_captured(tmp_path: Path) -> None:
    assert C2PATOOL is not None
    raw = await C2paToolInspector(C2PATOOL, temp_dir=tmp_path).inspect(SIGNED, extension="jpg")
    assert raw.tree and "Tree View" in raw.tree  # 0.28 lists assertions, 0.9 the hash too
    n = normalize_provenance(raw)
    assert n.assertions["hash_data"]["exclusion_count"] == 1


@needs_c2patool
async def test_signed_upload_exposes_depth_and_tree(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image", headers=headers, files={"file": ("C.jpg", SIGNED, "image/jpeg")}
    )
    aid = r.json()["id"]
    body = (await client.get(f"/analysis/{aid}/provenance", headers=headers)).json()
    assert body["tree"] and body["tree"].startswith("Tree View")
    assert body["normalized"]["assertions"]["hash_data"]["alg"] == "sha256"
    assert body["normalized"]["manifest_chain"][0]["signer"] == "C2PA Test Signing Cert"


# -- Phase 3: c2patool 0.28 output, settings file, remote manifests -------------------------


def _load_json(name: str) -> Any:
    import json

    return json.loads((FIXTURES / "json" / name).read_text("utf-8"))


def raw_0_28(*, trusted: bool = False, info: str | None = None) -> RawProvenance:
    summary = _load_json("summary_0.28.0.json")
    detailed = _load_json("detailed_trusted_0.28.0.json" if trusted else "detailed_0.28.0.json")
    return RawProvenance(
        engine="c2patool",
        engine_version="0.28.0",
        present=True,
        summary=summary,
        detailed=detailed,
        validation_status=summary.get("validation_status") or [],
        validation_results=detailed.get("validation_results"),
        validation_state=detailed.get("validation_state"),
        info=info,
    )


def test_0_28_output_normalises_with_trust_kept_apart() -> None:
    """0.28 checks trust by default and files an unlisted signer under *failure*; Verixa
    keeps integrity and trust apart, so the manifest is still intact (VERIFIED-eligible)."""
    n = normalize_provenance(raw_0_28())
    assert n.valid_signature is True and n.validation_failures == []
    assert n.validation["state"] == "Valid" and n.validation["source"] == "validation_results"
    fam = n.validation["active_manifest"]
    assert fam["failure"] == [] and "signingCredential.untrusted" in fam["trust"]
    assert "claimSignature.validated" in fam["success"]
    assert n.signer == "C2PA Test Signing Cert" and n.signer_common_name == "C2PA Signer"
    assert [a["action"] for a in n.actions] == ["c2pa.created", "c2pa.drawing"]  # actions.v2
    assert n.assertions["hash_data"]["exclusion_count"] == 1
    assert n.manifest_location == "embedded"


def test_0_28_trusted_state_is_carried() -> None:
    n = normalize_provenance(raw_0_28(trusted=True))
    assert n.validation["state"] == "Trusted"
    assert "signingCredential.untrusted" not in n.validation["active_manifest"]["trust"]


def test_info_reports_location_and_issues() -> None:
    info = (
        "Information for \nProvenance URI = https://cdn.example.net/manifests/abc.c2pa\n"
        "Manifest store size = 10 (1% of file size 100)\nValidation issues:\n"
        "   signingCredential.untrusted\nOne manifest"
    )
    n = normalize_provenance(raw_0_28(info=info))
    assert n.info["provenance_uri_kind"] == "remote" and n.info["issues"] is True
    assert n.manifest_location == "remote"
    assert (
        normalize_provenance(
            RawProvenance(engine="c2patool", engine_version="0.28.0", present=False)
        ).manifest_location
        == "none"
    )


def test_v2_software_agent_objects_are_flattened() -> None:
    raw = raw_signed()
    assert raw.summary is not None
    manifest = raw.summary["manifests"]["urn:a"]
    manifest["assertions"][1] = {
        "label": "c2pa.actions.v2",
        "data": {
            "actions": [
                {"action": "c2pa.edited", "softwareAgent": {"name": "Editor", "version": "2"}}
            ]
        },
    }
    n = normalize_provenance(raw)
    assert n.actions == [
        {"action": "c2pa.edited", "when": None, "software_agent": "Editor 2", "parameters": None}
    ]


def test_asset_args_pass_our_settings_and_never_a_url(tmp_path: Path) -> None:
    caps_new = C2paToolCapabilities(
        version="0.28.0", flags=frozenset({"--settings", "--info"}), subcommands=frozenset()
    )
    caps_old = C2paToolCapabilities(
        version="0.9.12", flags=frozenset({"--info"}), subcommands=frozenset()
    )
    asset = tmp_path / "c2pa-abc.jpg"
    inspector = C2paToolInspector("c2patool", temp_dir=tmp_path)
    args = inspector.asset_args(asset, caps_new)
    assert args == [str(asset), "--settings", str(SETTINGS_FILE)]
    assert inspector.asset_args(asset, caps_old) == [str(asset)]  # flag unknown -> not passed
    assert not any(a.startswith(("http://", "https://")) for a in args)
    # Explicit opt-in (never in production) leaves the engine defaults alone.
    opt_in = C2paToolInspector("c2patool", temp_dir=tmp_path, settings_file=None)
    assert opt_in.asset_args(asset, caps_new) == [str(asset)]


def test_shipped_settings_disable_engine_fetching() -> None:
    text = SETTINGS_FILE.read_text("utf-8")
    assert "remote_manifest_fetch = false" in text and "ocsp_fetch = false" in text


@needs_c2patool
async def test_c2patool_0_28_reports_state_and_settings_are_accepted(tmp_path: Path) -> None:
    assert C2PATOOL is not None
    inspector = C2paToolInspector(C2PATOOL, temp_dir=tmp_path)
    caps = await inspector.capabilities()
    raw = await inspector.inspect(SIGNED, extension="jpg")
    n = normalize_provenance(raw)
    assert n.valid_signature is True and n.validation_failures == []
    if caps.has_flag("--settings"):
        assert raw.validation_state in {"Valid", "Trusted"}
        assert raw.capabilities["version"].split(".")[1].isdigit()
        assert int(raw.capabilities["version"].split(".")[1]) >= 28
    else:  # an older engine on a developer machine
        assert raw.validation_state is None


# -- Phase 3: remote references the engine refuses to fetch ----------------------------------


def test_remote_host_from_error_keeps_only_the_host() -> None:
    from app.providers.provenance.c2patool import remote_host_from_error

    text = "Error: must fetch remote manifests from url https://cdn.example.net/m/abc.c2pa?t=1"
    assert remote_host_from_error(text) == "cdn.example.net"
    assert remote_host_from_error("Error: No claim found") is None
    assert remote_host_from_error("Unable to fetch cloud manifest. (file size = 998)") == (
        "unknown host"
    )


def test_engine_refusal_becomes_a_remote_location() -> None:
    raw = RawProvenance(
        engine="c2patool",
        engine_version="0.28.0",
        present=False,
        remote_manifest_host="cdn.example.net",
        warnings=["remote manifest reference not fetched"],
    )
    n = normalize_provenance(raw)
    assert n.has_c2pa is False and n.manifest_location == "remote"
    assert n.remote_manifest_host == "cdn.example.net"
    assert any("does not fetch remote manifests" in x for x in provenance_limitations(n))


@needs_c2patool
async def test_c2patool_never_fetches_a_remote_manifest(tmp_path: Path) -> None:
    """A JPEG that points at a hosted manifest: 0.28 with our settings refuses (host recorded);
    0.9.x has no manifest store to read and reports absence. Neither touches the network."""
    import socket

    from tests.test_lineage import jpeg_with_remote_reference

    assert C2PATOOL is not None
    inspector = C2paToolInspector(C2PATOOL, temp_dir=tmp_path)
    caps = await inspector.capabilities()
    original = socket.create_connection

    def refuse(*args: Any, **kwargs: Any) -> Any:
        raise AssertionError("network access attempted")

    socket.create_connection = refuse
    try:
        raw = await inspector.inspect(jpeg_with_remote_reference(), extension="jpg")
    finally:
        socket.create_connection = original
    assert raw.present is False
    if caps.has_flag("--settings"):
        assert raw.remote_manifest_host == "cdn.example.net"
        assert normalize_provenance(raw).manifest_location == "remote"
