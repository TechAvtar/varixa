"""JPEG ghost (double compression) detection, its step and its evidence."""

import io
from typing import Any

import pytest
from httpx import AsyncClient
from PIL import Image

from app.config import Settings
from app.services.evidence.engine import Observations, build_evidence
from app.services.image import double_compression as dc
from tests.test_compression import jpg, natural, png
from tests.test_evidence_engine import T, by_rule, forensics, rules
from tests.test_image_upload import auth_headers


def decoded(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        return img.convert("RGB")


def single(quality: int = 95, size: tuple[int, int] = (512, 384)) -> bytes:
    return jpg(natural(size), quality)


def double(first: int, second: int, size: tuple[int, int] = (512, 384)) -> bytes:
    return jpg(decoded(jpg(natural(size), first)), second)


def spliced(inner: int = 55, outer: int = 95) -> bytes:
    """A region decoded from a low-quality JPEG pasted into a high-quality one, saved once more."""
    base = decoded(single(outer))
    patch = decoded(jpg(natural((512, 384)), inner)).crop((128, 96, 320, 256))
    base.paste(patch, (128, 96))
    return jpg(base, outer)


# -- algorithm --------------------------------------------------------------------------------


def test_single_compression_has_no_ghost() -> None:
    r = dc.analyze_double_compression(single(95))
    assert r.last_quality == 95 and r.secondary_quality is None
    assert not r.detected and not r.anomaly and not r.periodic
    assert r.regions == [] and r.ghost_block_fraction < 0.01
    assert "No JPEG ghost" in r.observation


def test_whole_image_double_compression_is_detected_with_its_earlier_quality() -> None:
    r = dc.analyze_double_compression(double(60, 95))
    assert r.detected and not r.anomaly
    assert r.secondary_quality is not None and abs(r.secondary_quality - 60) <= 4
    assert r.secondary_depth >= 0.12 and r.periodic
    assert r.regions == []  # a ghost everywhere is history, not a localised anomaly
    assert "compressed at least twice" in r.observation


def test_localised_ghost_marks_the_pasted_region() -> None:
    r = dc.analyze_double_compression(spliced())
    assert r.anomaly and r.regions
    top = r.regions[0]
    # The pasted patch spans (128, 96) to (320, 256); the region must overlap it substantially.
    ox = max(0, min(top.x + top.width, 320) - max(top.x, 128))
    oy = max(0, min(top.y + top.height, 256) - max(top.y, 96))
    assert ox * oy >= 0.6 * 192 * 160
    assert r.ghost_quality_local is not None and r.ghost_quality_local <= 70
    assert not r.detected  # only part of the image carries the ghost


def test_large_images_are_centre_cropped_not_resampled() -> None:
    r = dc.analyze_double_compression(double(60, 95, size=(2400, 1800)), max_pixels=1_000_000)
    assert r.cropped and r.working_width * r.working_height <= 1_000_000
    assert r.working_width % 8 == 0 and r.working_height % 8 == 0
    assert r.detected and r.secondary_quality is not None
    assert "central part" in r.observation


def test_json_is_structured_and_free_of_pixels() -> None:
    j = dc.analyze_double_compression(double(60, 95)).to_json()
    assert j["method"] == "double_compression" and j["applicable"] is True
    assert len(j["qualities"]) == len(j["curve"]) == len(dc.QUALITIES)
    assert "visualization_png" not in j and j["limitations"]
    na = dc.not_applicable_json("PNG")
    assert na["applicable"] is False and na["format"] == "PNG"


def test_thresholds_are_parameters() -> None:
    strict = dc.analyze_double_compression(double(60, 95), min_depth=0.9)
    assert strict.secondary_quality is None
    loose = dc.analyze_double_compression(double(60, 95), periodicity_min=1e6)
    assert not loose.periodic and loose.detected  # the ghost curve alone still detects it


# -- evidence ---------------------------------------------------------------------------------


def _dcj(**kw: Any) -> dict[str, Any]:
    base = {
        "applicable": True,
        "version": "v1",
        "anomaly": False,
        "detected": False,
        "observation": "quiet",
        "primary_quality": 94,
        "secondary_quality": None,
        "ghost_block_fraction": 0.0,
        "ghost_quality_local": None,
        "regions": [],
        "periodic": False,
    }
    return {**base, **kw}


def test_localised_ghost_shares_the_ela_family_and_a_global_ghost_is_history() -> None:
    local = forensics(
        double_compression_json=_dcj(
            anomaly=True,
            ghost_quality_local=56,
            ghost_block_fraction=0.15,
            regions=[{"x": 128, "y": 96, "width": 192, "height": 160, "blocks": 118, "depth": 0.3}],
        )
    )
    drafts = build_evidence(Observations("image", forensics=local), T)
    d = by_rule(drafts, "forensics.double-compression.localized")
    assert d.level == "POSSIBLE" and "quality 56" in d.claim
    assert d.data["family"] == "error-level/compression"
    assert "forensics.multiple" not in rules(drafts)  # one family only, even with ELA quiet

    glob = forensics(double_compression_json=_dcj(detected=True, secondary_quality=60))
    g = by_rule(
        build_evidence(Observations("image", forensics=glob), T),
        "forensics.double-compression.global",
    )
    assert g.level == "POSSIBLE" and "quality 60" in g.claim and "routine" in (g.limitation or "")

    quiet = build_evidence(
        Observations("image", forensics=forensics(double_compression_json=_dcj())), T
    )
    assert by_rule(quiet, "forensics.double-compression.none").level == "UNKNOWN"
    na = forensics(double_compression_json={"applicable": False, "reason": "not a JPEG"})
    assert (
        by_rule(
            build_evidence(Observations("image", forensics=na), T),
            "forensics.double-compression.na",
        ).level
        == "UNKNOWN"
    )


# -- pipeline + API ---------------------------------------------------------------------------


async def test_spliced_jpeg_upload_reports_a_localised_ghost_with_a_map(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("s.jpg", spliced(), "image/jpeg")},
    )
    aid = r.json()["id"]
    detail = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    step = next(s for s in detail["steps"] if s["name"] == "double_compression")
    assert step["status"] == "completed" and step["details"]["artifact"] == "ghost.png"
    f = (await client.get(f"/analysis/{aid}/forensics", headers=headers)).json()
    d = f["double_compression"]
    assert d["method"] == "double_compression" and d["anomaly"] is True and d["regions"]
    art = next(a for a in f["artifacts"] if a["method"] == "double_compression")
    assert art["content_type"] == "image/png" and "sig=" in art["url"]
    assert (await client.get(art["url"])).status_code == 200
    evidence = (await client.get(f"/analysis/{aid}/evidence", headers=headers)).json()["items"]
    assert any(e["rule"] == "forensics.double-compression.localized" for e in evidence)


async def test_png_is_recorded_as_not_applicable(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("p.png", png(natural((64, 48))), "image/png")},
    )
    aid = r.json()["id"]
    f = (await client.get(f"/analysis/{aid}/forensics", headers=headers)).json()
    assert f["double_compression"] is None
    assert any(s["method"] == "double_compression" for s in f["skipped"])
    assert not any(a["method"] == "double_compression" for a in f["artifacts"])


@pytest.mark.parametrize("quality", [50, 100])
def test_quality_range_edges_do_not_crash(quality: int) -> None:
    r = dc.analyze_double_compression(single(quality, size=(128, 96)))
    assert r.primary_quality in dc.QUALITIES
