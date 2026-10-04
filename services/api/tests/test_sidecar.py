"""T050: optional C2PA sidecar (.c2pa) uploaded beside an image."""

from pathlib import Path
from typing import Any

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models import AnalysisFile
from app.providers.provenance import C2paToolInspector, find_c2patool
from app.providers.provenance.c2patool import C2paToolCapabilities
from app.services.image.sidecar import InvalidSidecarError, validate_sidecar
from app.services.image.validation import ImageTooLargeError
from tests.test_image_upload import auth_headers, make_image

FIXTURES = Path(__file__).parent / "fixtures" / "c2pa"
IMAGE = (FIXTURES / "sidecar_sample.jpg").read_bytes()
SIDECAR = (FIXTURES / "sidecar_sample.c2pa").read_bytes()
C2PATOOL = find_c2patool()
needs_c2patool = pytest.mark.skipif(C2PATOOL is None, reason="c2patool not installed")


def _files(sidecar: bytes | None = SIDECAR, name: str = "manifest.c2pa") -> dict[str, Any]:
    files: dict[str, Any] = {"file": ("photo.jpg", IMAGE, "image/jpeg")}
    if sidecar is not None:
        files["sidecar"] = (name, sidecar, "application/octet-stream")
    return files


async def _rows(client: AsyncClient, analysis_id: str) -> list[AnalysisFile]:
    import uuid

    app = client._transport.app  # type: ignore[attr-defined]
    async with app.state.session_factory() as db:
        stmt = select(AnalysisFile).where(AnalysisFile.analysis_id == uuid.UUID(analysis_id))
        return list((await db.execute(stmt)).scalars().all())


# -- validation ------------------------------------------------------------------------------------


def test_validate_sidecar_accepts_a_manifest_store_and_nothing_else() -> None:
    v = validate_sidecar(SIDECAR, max_bytes=4 * 1024 * 1024)
    assert v.size_bytes == len(SIDECAR) and len(v.sha256) == 64
    for bad in (b"", b"tiny", IMAGE, b"\x00" * 200, b"%PDF-1.7" + b"\x00" * 200):
        with pytest.raises(InvalidSidecarError):
            validate_sidecar(bad, max_bytes=4 * 1024 * 1024)
    with pytest.raises(ImageTooLargeError):
        validate_sidecar(SIDECAR, max_bytes=1024)


def test_asset_args_name_the_sidecar_only_when_the_engine_supports_it(tmp_path: Path) -> None:
    inspector = C2paToolInspector("c2patool", temp_dir=tmp_path, settings_file=None)
    asset, sidecar = tmp_path / "c2pa-abc.jpg", tmp_path / "c2pa-abc.c2pa"
    new = C2paToolCapabilities(
        version="0.28.0", flags=frozenset({"--external-manifest"}), subcommands=frozenset()
    )
    old = C2paToolCapabilities(version="0.9.12", flags=frozenset(), subcommands=frozenset())
    assert inspector.asset_args(asset, new, sidecar) == [
        str(asset),
        "--external-manifest",
        str(sidecar),
    ]
    assert inspector.asset_args(asset, old, sidecar) == [str(asset)]  # same-stem pickup instead
    assert inspector.asset_args(asset, new) == [str(asset)]


# -- upload ----------------------------------------------------------------------------------------


async def test_sidecar_is_stored_with_its_own_role_and_hash_named_key(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    hostile = "../../evil name; rm -rf.c2pa"
    r = await client.post("/analysis/image", headers=headers, files=_files(name=hostile))
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    rows = await _rows(client, aid)
    roles = {f.role: f for f in rows}
    assert set(roles) == {"original", "sidecar"}
    sc = roles["sidecar"]
    assert sc.object_key.endswith(f"{sc.sha256}.c2pa") and "evil" not in sc.object_key
    assert sc.original_filename is None and sc.mime_type == "application/c2pa"
    assert sc.size_bytes == len(SIDECAR)
    # The API still describes the image as the analysed file.
    detail = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    assert detail["file"]["mime_type"] == "image/jpeg" and detail["status"] == "completed"
    link = (await client.get(f"/analysis/{aid}/file", headers=headers)).json()
    assert ".c2pa" not in link["url"]


async def test_invalid_sidecar_is_refused_and_nothing_is_created(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image", headers=headers, files=_files(sidecar=b"not a manifest " * 20)
    )
    assert r.status_code == 422 and r.json()["error"]["code"] == "INVALID_FILE"
    assert "not a C2PA manifest store" in r.json()["error"]["message"]
    listing = (await client.get("/analysis", headers=headers)).json()
    assert listing["total"] == 0


async def test_oversized_and_disabled_sidecars_are_refused(
    client: AsyncClient, migrated_settings: Any
) -> None:
    headers = await auth_headers(client)
    migrated_settings.sidecar_max_bytes = 1024
    r = await client.post("/analysis/image", headers=headers, files=_files())
    assert r.status_code == 413 and r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
    migrated_settings.sidecar_max_bytes = 4 * 1024 * 1024
    migrated_settings.sidecar_upload_enabled = False
    r = await client.post("/analysis/image", headers=headers, files=_files())
    assert r.status_code == 422 and "disabled" in r.json()["error"]["message"]
    assert (await client.get("/analysis", headers=headers)).json()["total"] == 0


async def test_upload_without_sidecar_is_unchanged(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.png", make_image("PNG"), "image/png")},
    )
    assert r.status_code == 201
    rows = await _rows(client, r.json()["id"])
    assert [f.role for f in rows] == ["original"]


async def test_deleting_the_analysis_removes_the_sidecar_object(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    aid = (await client.post("/analysis/image", headers=headers, files=_files())).json()["id"]
    rows = await _rows(client, aid)
    storage = client._transport.app.state.storage  # type: ignore[attr-defined]
    keys = [f.object_key for f in rows]
    assert len(keys) == 2 and all([await storage.exists(k) for k in keys])
    assert (await client.delete(f"/analysis/{aid}", headers=headers)).status_code == 204
    assert not any([await storage.exists(k) for k in keys])


# -- engine ----------------------------------------------------------------------------------------


@needs_c2patool
async def test_sidecar_manifest_is_validated_against_the_image(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    aid = (await client.post("/analysis/image", headers=headers, files=_files())).json()["id"]
    body = (await client.get(f"/analysis/{aid}/provenance", headers=headers)).json()
    n = body["normalized"]
    assert n["has_c2pa"] and n["valid_signature"] is True and n["manifest_location"] == "sidecar"
    assert any("sidecar file supplied with the upload" in x for x in body["limitations"])
    ev = (await client.get(f"/analysis/{aid}/evidence", headers=headers)).json()
    valid = next(i for i in ev["items"] if i["rule"] == "provenance.valid")
    assert valid["level"] == "VERIFIED" and valid["data"]["manifest_location"] == "sidecar"
    assert "row:analysis_files" in valid["refs"] and "sidecar file" in valid["limitation"]


@needs_c2patool
async def test_sidecar_for_another_image_does_not_validate(client: AsyncClient) -> None:
    """The manifest's data hash binds it to its own image: paired with other bytes it fails."""
    headers = await auth_headers(client)
    files = {
        "file": ("other.jpg", make_image("JPEG", (320, 240)), "image/jpeg"),
        "sidecar": ("m.c2pa", SIDECAR, "application/octet-stream"),
    }
    aid = (await client.post("/analysis/image", headers=headers, files=files)).json()["id"]
    body = (await client.get(f"/analysis/{aid}/provenance", headers=headers)).json()
    n = body["normalized"]
    assert n["has_c2pa"] and n["valid_signature"] is False and n["manifest_location"] == "sidecar"
    ev = (await client.get(f"/analysis/{aid}/evidence", headers=headers)).json()
    rules = {i["rule"]: i["level"] for i in ev["items"]}
    assert rules.get("provenance.invalid") == "POSSIBLE" and "provenance.valid" not in rules
