import io
import uuid
from typing import Any

import numpy as np
import pytest
from httpx import AsyncClient
from PIL import Image

from app.config import Settings
from app.services.image import ela
from tests.test_image_upload import auth_headers, make_image

# -- fixtures ------------------------------------------------------------------------------------


def noisy_rgb(size: tuple[int, int], seed: int = 1) -> Image.Image:
    rng = np.random.default_rng(seed)
    arr = rng.integers(0, 256, size=(size[1], size[0], 3), dtype=np.uint8)
    return Image.fromarray(arr, "RGB")


def jpeg_bytes(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def spliced_jpeg() -> bytes:
    """A low-quality JPEG background with a never-compressed noisy patch pasted in, saved at q95.

    The pasted region has no prior JPEG history, so it re-compresses very differently.
    """
    base = noisy_rgb((512, 384), seed=2)
    base = Image.open(io.BytesIO(jpeg_bytes(base, 40))).convert("RGB")
    base = Image.open(io.BytesIO(jpeg_bytes(base, 40))).convert("RGB")
    patch = noisy_rgb((96, 80), seed=3)
    base.paste(patch, (300, 200))
    return jpeg_bytes(base, 95)


# -- pure computation ----------------------------------------------------------------------------


def test_uniform_jpeg_has_no_regions_and_low_error() -> None:
    data = jpeg_bytes(Image.new("RGB", (256, 192), (120, 130, 140)), 90)
    r = ela.compute_ela(data)
    assert r.mean_error < 1.0 and r.regions == [] and r.anomaly is False
    assert r.outlier_block_fraction == 0.0
    assert "little discriminating power" in r.observation
    assert r.confidence == "low" and r.limitations == ela.LIMITATIONS
    assert (r.working_width, r.working_height) == (256, 192) and not r.downscaled


def test_spliced_region_is_localised_and_flagged() -> None:
    r = ela.compute_ela(spliced_jpeg())
    assert r.anomaly is True and r.regions
    top = r.regions[0]
    # The pasted patch sits at (300, 200) 96x80; the bounding box must cover most of it.
    assert 260 <= top.x <= 310 and 160 <= top.y <= 210
    assert top.x + top.width >= 380 and top.y + top.height >= 265
    assert top.value > r.mean_error
    assert "localised region" in r.observation


def test_visualization_is_a_png_at_working_size_without_original_pixels() -> None:
    src = noisy_rgb((200, 100))
    r = ela.compute_ela(jpeg_bytes(src, 85))
    with Image.open(io.BytesIO(r.visualization_png)) as vis:
        assert vis.format == "PNG" and vis.size == (200, 100)
        arr = np.asarray(vis.convert("RGB"))
    # An amplified difference map is not a copy of the source.
    assert not np.array_equal(arr, np.asarray(src))


def test_large_image_is_downscaled_and_regions_are_in_original_coords() -> None:
    data = jpeg_bytes(noisy_rgb((1200, 600)), 80)
    r = ela.compute_ela(data, max_side=300)
    assert r.downscaled and (r.working_width, r.working_height) == (300, 150)
    assert (r.original_width, r.original_height) == (1200, 600)
    for region in r.regions:
        assert 0 <= region.x < 1200 and 0 <= region.y < 600
    assert "downscaled" in r.observation


def test_json_is_structured_and_free_of_pixels() -> None:
    j = ela.compute_ela(spliced_jpeg()).to_json()
    assert j["method"] == "ela" and j["version"] == ela.ELA_VERSION and j["applicable"] is True
    assert set(j) >= {"observation", "confidence", "limitations", "regions", "anomaly"}
    assert "visualization_png" not in j
    na = ela.not_applicable_json("PNG")
    assert na["applicable"] is False and na["reason"] and na["format"] == "PNG"


def test_thresholds_are_parameters() -> None:
    data = spliced_jpeg()
    strict = ela.compute_ela(data, anomaly_max_fraction=0.0)
    assert strict.anomaly is False and strict.regions  # regions reported, band excludes them


# -- pipeline + API ------------------------------------------------------------------------------


async def _wait_completed(client: AsyncClient, headers: dict[str, str], aid: str) -> dict[str, Any]:
    body: dict[str, Any] = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    assert body["status"] in ("completed", "failed"), body["status"]
    return body


async def test_jpeg_upload_runs_ela_and_exposes_findings(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("s.jpg", spliced_jpeg(), "image/jpeg")},
    )
    aid = r.json()["id"]
    body = await _wait_completed(client, headers, aid)
    step = next(s for s in body["steps"] if s["name"] == "ela")
    assert step["status"] == "completed" and step["details"]["artifact"] == "ela.png"

    f = (await client.get(f"/analysis/{aid}/forensics", headers=headers)).json()
    assert f["ela"]["method"] == "ela" and f["ela"]["anomaly"] is True
    assert f["ela"]["confidence"] == "low" and f["ela"]["limitations"]
    assert f["skipped"] == [] and f["limitations"]
    art = next(a for a in f["artifacts"] if a["method"] == "ela")
    assert art["method"] == "ela" and art["content_type"] == "image/png"
    assert art["url"].startswith("http") and "sig=" in art["url"] and "object_key" not in art

    # The signed link serves the PNG without any auth header.
    png = await client.get(art["url"])
    assert png.status_code == 200 and png.headers["content-type"].startswith("image/png")
    with Image.open(io.BytesIO(png.content)) as vis:
        assert vis.size == (art["width"], art["height"])


async def test_non_jpeg_is_recorded_as_not_applicable(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.png", make_image("PNG"), "image/png")},
    )
    aid = r.json()["id"]
    body = await _wait_completed(client, headers, aid)
    step = next(s for s in body["steps"] if s["name"] == "ela")
    assert step["status"] == "skipped" and body["status"] == "completed"
    f = (await client.get(f"/analysis/{aid}/forensics", headers=headers)).json()
    assert f["ela"] is None and not any(a["method"] == "ela" for a in f["artifacts"])
    assert f["skipped"] == [{"method": "ela", "reason": ela.NOT_APPLICABLE_REASON}]


async def test_forensics_endpoint_enforces_ownership_and_404s(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    owner = await auth_headers(client, "o@example.com")
    r = await client.post(
        "/analysis/image",
        headers=owner,
        files={"file": ("a.jpg", make_image("JPEG"), "image/jpeg")},
    )
    aid = r.json()["id"]
    intruder = await auth_headers(client, "i@example.com")
    assert (await client.get(f"/analysis/{aid}/forensics", headers=intruder)).status_code == 404
    assert (
        await client.get(f"/analysis/{uuid.uuid4()}/forensics", headers=owner)
    ).status_code == 404
    assert (await client.get(f"/analysis/{aid}/forensics")).status_code == 401
    # Text analyses have no forensics row.
    t = await client.post("/analysis/text", headers=owner, json={"text": "hello world " * 20})
    assert (
        await client.get(f"/analysis/{t.json()['id']}/forensics", headers=owner)
    ).status_code == 404


async def test_delete_removes_ela_artifact(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image", headers=headers, files={"file": ("a.jpg", spliced_jpeg(), "image/jpeg")}
    )
    aid = r.json()["id"]
    await _wait_completed(client, headers, aid)
    arts = (await client.get(f"/analysis/{aid}/forensics", headers=headers)).json()["artifacts"]
    url = next(a for a in arts if a["method"] == "ela")["url"]
    assert (await client.get(url)).status_code == 200
    assert (await client.delete(f"/analysis/{aid}", headers=headers)).status_code == 204
    assert (await client.get(url)).status_code == 404


@pytest.mark.parametrize("quality", [50, 100])
def test_quality_bounds_accepted(quality: int) -> None:
    r = ela.compute_ela(jpeg_bytes(noisy_rgb((64, 64)), 80), quality=quality)
    assert r.quality == quality
