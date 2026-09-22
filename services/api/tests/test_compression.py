import io
from typing import Any

import numpy as np
import pytest
from httpx import AsyncClient
from PIL import Image

from app.config import Settings
from app.services.image import compression
from tests.test_image_upload import auth_headers, make_image


def natural(size: tuple[int, int], seed: int = 1) -> Image.Image:
    """Smooth gradients plus mild noise: blocking is visible at low quality, unlike pure noise."""
    rng = np.random.default_rng(seed)
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    base = 90 + 60 * np.sin(xx / 37.0) + 50 * np.cos(yy / 23.0) + rng.normal(0, 12, (h, w))
    rgb = np.stack([base, base * 0.9 + 10, base * 0.8 + 20], axis=2)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")


def jpg(img: Image.Image, quality: int, **kw: Any) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, **kw)
    return buf.getvalue()


def png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# -- encoding facts -------------------------------------------------------------------------------


@pytest.mark.parametrize("quality", [30, 50, 75, 92, 100])
def test_estimated_quality_matches_pillow_standard_tables(quality: int) -> None:
    r = compression.analyze_compression(jpg(natural((256, 192)), quality))
    assert r.encoding is not None
    assert r.encoding.estimated_quality == quality and r.encoding.standard_tables
    assert r.encoding.luma_table_error == 0.0 and r.encoding.table_count == 2


def test_subsampling_and_progressive_are_read_from_the_file() -> None:
    r = compression.analyze_compression(
        jpg(natural((256, 192)), 80, subsampling=0, progressive=True)
    )
    assert r.encoding is not None
    assert r.encoding.subsampling == "4:4:4" and r.encoding.progressive is True
    assert r.encoding.has_jfif is True
    r2 = compression.analyze_compression(jpg(natural((256, 192)), 80, subsampling=2))
    assert r2.encoding is not None and r2.encoding.subsampling == "4:2:0"
    assert r2.encoding.progressive is False


def test_custom_tables_are_reported_as_custom() -> None:
    custom = [max(1, int(v * 1.3)) for v in compression.STD_LUMA]
    r = compression.analyze_compression(
        jpg(natural((256, 192)), 75, qtables={0: custom, 1: custom})
    )
    assert r.encoding is not None and r.encoding.standard_tables is False
    assert r.encoding.luma_table_error is not None and r.encoding.luma_table_error > 0
    assert "custom quantisation tables" in r.observation


# -- block grid -----------------------------------------------------------------------------------


def test_single_low_quality_save_has_aligned_grid_and_no_anomaly() -> None:
    r = compression.analyze_compression(jpg(natural((512, 384)), 40))
    assert r.grid.measured and r.grid.detected_aligned and not r.grid.detected_offset
    assert r.anomaly is False and r.prior_jpeg_grid is False
    assert "aligned with the file's block boundaries" in r.observation


def test_crop_and_resave_shows_offset_grid() -> None:
    first = Image.open(io.BytesIO(jpg(natural((512, 384)), 40))).convert("RGB")
    cropped = first.crop((3, 5, 403, 305))
    r = compression.analyze_compression(jpg(cropped, 95))
    assert r.anomaly is True and r.grid.detected_offset
    # Old boundaries at x = 8k land at x' = 8k - 3 (phase 5); y = 8k - 5 (phase 3).
    assert (r.grid.offset_x, r.grid.offset_y) == (5, 3)
    assert "offset by (5, 3)" in r.observation
    assert r.confidence == "low" and r.to_json()["limitations"] == compression.LIMITATIONS


def test_png_from_jpeg_carries_prior_grid_but_clean_png_does_not() -> None:
    src = natural((512, 384))
    was_jpeg = Image.open(io.BytesIO(jpg(src, 40))).convert("RGB")
    r = compression.analyze_compression(png(was_jpeg))
    assert r.encoding is None and r.lossless_container and r.prior_jpeg_grid is True
    assert r.anomaly is False and "not a JPEG" in r.observation
    clean = compression.analyze_compression(png(src))
    assert clean.prior_jpeg_grid is False and "No 8x8 blocking grid" in clean.observation


def test_small_images_skip_the_grid_measurement() -> None:
    r = compression.analyze_compression(jpg(natural((40, 40)), 60))
    assert r.grid.measured is False and r.anomaly is False
    assert "too small" in r.observation


def test_threshold_is_a_parameter() -> None:
    data = jpg(natural((512, 384)), 40)
    assert (
        compression.analyze_compression(data, grid_min_strength=5.0).grid.detected_aligned is False
    )


def test_json_shape() -> None:
    j = compression.analyze_compression(jpg(natural((128, 96)), 70)).to_json()
    assert j["method"] == "compression" and j["applicable"] is True
    assert set(j) >= {"encoding", "grid", "anomaly", "prior_jpeg_grid", "observation", "confidence"}


# -- pipeline + API -------------------------------------------------------------------------------


async def test_upload_runs_compression_and_exposes_findings(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await auth_headers(client)
    first = Image.open(io.BytesIO(jpg(natural((512, 384)), 40))).convert("RGB")
    data = jpg(first.crop((3, 5, 403, 305)), 95)
    r = await client.post(
        "/analysis/image", headers=headers, files={"file": ("c.jpg", data, "image/jpeg")}
    )
    aid = r.json()["id"]
    body = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    step = next(s for s in body["steps"] if s["name"] == "compression")
    assert step["status"] == "completed" and step["details"]["estimated_quality"] == 95
    f = (await client.get(f"/analysis/{aid}/forensics", headers=headers)).json()
    c = f["compression"]
    assert c["method"] == "compression" and c["anomaly"] is True
    assert c["encoding"]["subsampling"] == "4:2:0" and c["grid"]["offset_x"] == 5
    assert c["confidence"] == "low" and c["limitations"]
    # ELA and compression share the row without clobbering each other.
    assert f["ela"] is not None


async def test_png_upload_runs_compression_without_encoding(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.png", make_image("PNG"), "image/png")},
    )
    aid = r.json()["id"]
    f = (await client.get(f"/analysis/{aid}/forensics", headers=headers)).json()
    assert f["compression"]["encoding"] is None and f["compression"]["format"] == "PNG"
    assert f["ela"] is None and any(s["method"] == "ela" for s in f["skipped"])
