"""Embedded-thumbnail comparison: extraction, comparison, step and evidence."""

import io
import struct
from typing import Any

import numpy as np
from httpx import AsyncClient
from PIL import Image

from app.config import Settings
from app.services.evidence.engine import Observations, build_evidence
from app.services.image import thumbnail as th
from tests.test_compression import jpg, natural
from tests.test_evidence_engine import T, by_rule, forensics, rules
from tests.test_image_upload import auth_headers


def tiff_with_thumbnail(thumb_jpeg: bytes) -> bytes:
    """Minimal little-endian TIFF: IFD0 with one tag, IFD1 pointing at a JPEG thumbnail."""
    ifd0_offset = 8
    ifd0 = (
        struct.pack("<H", 1)
        + struct.pack("<HHII", 0x0112, 3, 1, 1)
        + struct.pack("<I", ifd0_offset + 2 + 12 + 4)
    )
    ifd1_offset = ifd0_offset + len(ifd0)
    data_offset = ifd1_offset + 2 + 24 + 4
    ifd1 = (
        struct.pack("<H", 2)
        + struct.pack("<HHII", 0x0201, 4, 1, data_offset)
        + struct.pack("<HHII", 0x0202, 4, 1, len(thumb_jpeg))
        + struct.pack("<I", 0)
    )
    return b"II*\x00" + struct.pack("<I", ifd0_offset) + ifd0 + ifd1 + thumb_jpeg


def with_thumbnail(main: Image.Image, thumb_source: Image.Image, quality: int = 92) -> bytes:
    """``main`` saved as JPEG with an EXIF thumbnail rendered from ``thumb_source``."""
    tb = io.BytesIO()
    w = 160
    thumb_source.resize((w, max(1, round(w * thumb_source.height / thumb_source.width)))).save(
        tb, format="JPEG", quality=85
    )
    out = io.BytesIO()
    main.save(
        out,
        format="JPEG",
        quality=quality,
        exif=b"Exif\x00\x00" + tiff_with_thumbnail(tb.getvalue()),
    )
    return out.getvalue()


def other_picture(size: tuple[int, int] = (640, 480)) -> Image.Image:
    """Genuinely different content (not just different noise)."""
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    base = 120 + 80 * np.sin((xx + yy) / 13.0) * np.cos(yy / 41.0)
    rgb = np.stack([base, 255 - base, base * 0.5], axis=2)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")


PHOTO = natural((640, 480), 3)


# -- extraction -------------------------------------------------------------------------------


def test_extracts_the_ifd1_thumbnail_and_tolerates_absence_and_damage() -> None:
    data = with_thumbnail(PHOTO, PHOTO)
    blob = th.extract_exif_thumbnail(data)
    assert blob is not None and blob[:2] == b"\xff\xd8"
    with Image.open(io.BytesIO(blob)) as t:
        assert t.size == (160, 120)
    assert th.extract_exif_thumbnail(jpg(PHOTO, 90)) is None  # no EXIF at all
    assert th.extract_exif_thumbnail(b"\xff\xd8\xff\xe1\x00\x08Exif\x00\x00II") is None
    assert th.extract_exif_thumbnail(b"not an image") is None
    truncated = data[: data.index(b"\xff\xd8", 10) + 5]
    assert th.extract_exif_thumbnail(truncated) is None


# -- comparison -------------------------------------------------------------------------------


def test_matching_thumbnail_is_consistent() -> None:
    r = th.compare_thumbnail(with_thumbnail(PHOTO, PHOTO))
    assert r is not None and r.correlation > 0.98
    assert not r.flagged and r.best_transform == "none" and r.regions == []
    assert "matches the current image" in r.observation


def test_local_edit_after_thumbnail_is_localised() -> None:
    edited = PHOTO.copy()
    edited.paste(Image.new("RGB", (160, 120), (250, 250, 250)), (300, 200))
    r = th.compare_thumbnail(with_thumbnail(edited, PHOTO))
    assert r is not None and r.anomaly and not r.mismatch_global
    assert r.correlation_outside_regions > r.correlation
    top = r.regions[0]
    ox = max(0, min(top.x + top.width, 460) - max(top.x, 300))
    oy = max(0, min(top.y + top.height, 320) - max(top.y, 200))
    assert ox * oy >= 0.5 * 160 * 120
    assert "localised region" in r.observation


def test_different_content_is_a_global_mismatch() -> None:
    r = th.compare_thumbnail(with_thumbnail(other_picture(), PHOTO))
    assert r is not None and r.mismatch_global and not r.anomaly
    assert r.correlation < 0.9 and "does not depict" in r.observation


def test_flip_and_crop_after_thumbnail_are_geometry_mismatches() -> None:
    flipped = th.compare_thumbnail(
        with_thumbnail(PHOTO.transpose(Image.Transpose.FLIP_LEFT_RIGHT), PHOTO)
    )
    assert flipped is not None and flipped.orientation_mismatch
    assert flipped.best_transform == "flip_h" and flipped.best_transform_correlation > 0.98
    assert not flipped.mismatch_global and "flipped or rotated" in flipped.observation
    cropped = th.compare_thumbnail(with_thumbnail(PHOTO.crop((0, 0, 480, 480)), PHOTO))
    assert cropped is not None and cropped.aspect_mismatch and cropped.flagged
    assert "Aspect ratios differ" in cropped.observation


def test_json_is_structured_and_free_of_pixels() -> None:
    r = th.compare_thumbnail(with_thumbnail(PHOTO, PHOTO))
    assert r is not None
    j = r.to_json()
    assert j["method"] == "thumbnail" and j["applicable"] and j["has_thumbnail"]
    assert "visualization_png" not in j and "thumbnail_png" not in j
    with Image.open(io.BytesIO(r.visualization_png)) as vis:
        assert vis.size[0] >= 160 and vis.format == "PNG"
    with Image.open(io.BytesIO(r.thumbnail_png)) as emb:
        assert emb.size == (160, 120)


# -- evidence ---------------------------------------------------------------------------------


def _thj(**kw: Any) -> dict[str, Any]:
    base = {
        "applicable": True,
        "version": "v1",
        "observation": "quiet",
        "correlation": 0.99,
        "correlation_outside_regions": 0.99,
        "best_transform": "none",
        "aspect_ratio_image": 1.333,
        "aspect_ratio_thumbnail": 1.333,
        "aspect_mismatch": False,
        "orientation_mismatch": False,
        "mismatch_global": False,
        "anomaly": False,
        "regions": [],
    }
    return {**base, **kw}


def test_thumbnail_rules_and_family() -> None:
    quiet = build_evidence(Observations("image", forensics=forensics(thumbnail_json=_thj())), T)
    assert by_rule(quiet, "forensics.thumbnail.consistent").level == "UNKNOWN"

    region = forensics(
        thumbnail_json=_thj(
            anomaly=True,
            correlation=0.7,
            regions=[
                {"x": 300, "y": 200, "width": 160, "height": 120, "blocks": 9, "mean_diff": 2.1}
            ],
        )
    )
    d = by_rule(
        build_evidence(Observations("image", forensics=region), T), "forensics.thumbnail.region"
    )
    assert d.level == "POSSIBLE" and d.data["family"] == "thumbnail"

    swapped = forensics(thumbnail_json=_thj(mismatch_global=True, correlation=0.2))
    assert (
        by_rule(
            build_evidence(Observations("image", forensics=swapped), T),
            "forensics.thumbnail.mismatch",
        ).level
        == "POSSIBLE"
    )

    geometry = forensics(thumbnail_json=_thj(orientation_mismatch=True, best_transform="flip_h"))
    g = by_rule(
        build_evidence(Observations("image", forensics=geometry), T), "forensics.thumbnail.geometry"
    )
    assert "flipped or rotated" in g.claim

    # Thumbnail is an independent family: together with an ELA anomaly it reaches STRONG.
    from tests.test_evidence_engine import ELA_ANOMALY

    both = forensics(
        ela_json=ELA_ANOMALY, thumbnail_json=_thj(mismatch_global=True, correlation=0.2)
    )
    drafts = build_evidence(Observations("image", forensics=both), T)
    assert by_rule(drafts, "forensics.multiple").level == "STRONG"
    assert set(by_rule(drafts, "forensics.multiple").data["families"]) == {
        "error-level/compression",
        "thumbnail",
    }

    na = forensics(thumbnail_json={"applicable": False, "reason": "none"})
    assert (
        by_rule(
            build_evidence(Observations("image", forensics=na), T), "forensics.thumbnail.na"
        ).level
        == "UNKNOWN"
    )
    assert "forensics.thumbnail.consistent" not in rules(
        build_evidence(Observations("image", forensics=na), T)
    )


# -- pipeline + API ---------------------------------------------------------------------------


async def test_upload_with_stale_thumbnail_exposes_finding_and_both_artifacts(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await auth_headers(client)
    edited = PHOTO.copy()
    edited.paste(Image.new("RGB", (160, 120), (250, 250, 250)), (300, 200))
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("t.jpg", with_thumbnail(edited, PHOTO), "image/jpeg")},
    )
    aid = r.json()["id"]
    detail = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    step = next(s for s in detail["steps"] if s["name"] == "thumbnail")
    assert step["status"] == "completed" and step["details"]["anomaly"] is True
    f = (await client.get(f"/analysis/{aid}/forensics", headers=headers)).json()
    t = f["thumbnail"]
    assert t["method"] == "thumbnail" and t["anomaly"] and t["flagged"] and t["regions"]
    methods = {a["method"] for a in f["artifacts"]}
    assert {"thumbnail", "thumbnail_embedded"} <= methods
    for a in f["artifacts"]:
        if a["method"].startswith("thumbnail"):
            assert (await client.get(a["url"])).status_code == 200
    evidence = (await client.get(f"/analysis/{aid}/evidence", headers=headers)).json()["items"]
    assert any(e["rule"] == "forensics.thumbnail.region" for e in evidence)


async def test_upload_without_thumbnail_is_skipped_not_failed(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("n.jpg", jpg(natural((64, 48)), 90), "image/jpeg")},
    )
    aid = r.json()["id"]
    detail = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    step = next(s for s in detail["steps"] if s["name"] == "thumbnail")
    assert step["status"] == "skipped"
    f = (await client.get(f"/analysis/{aid}/forensics", headers=headers)).json()
    assert f["thumbnail"] is None
    assert any(s["method"] == "thumbnail" for s in f["skipped"])
    assert not any(a["method"].startswith("thumbnail") for a in f["artifacts"])
