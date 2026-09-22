import io

import numpy as np
from httpx import AsyncClient
from PIL import Image

from app.config import Settings
from app.services.image import resampling
from tests.test_image_upload import auth_headers


def natural(size: tuple[int, int], seed: int = 1) -> Image.Image:
    """Gradients, a diagonal texture and mild noise: no periodicity of its own."""
    rng = np.random.default_rng(seed)
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    base = (
        90
        + 60 * np.sin(xx / 37.0)
        + 50 * np.cos(yy / 23.0)
        + 30 * np.sin((xx + yy) / 11.0)
        + rng.normal(0, 12, (h, w))
    )
    rgb = np.stack([base, base * 0.9 + 10, base * 0.8 + 20], axis=2)
    return Image.fromarray(np.clip(rgb, 0, 255).astype(np.uint8), "RGB")


def png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def jpg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


SRC = natural((900, 700))


def test_unresampled_images_have_no_peaks() -> None:
    for data in (png(SRC), jpg(SRC, 75), jpg(SRC, 40)):
        r = resampling.analyze_resampling(data)
        assert r.measured and r.tiles == 6 and r.detected is False and r.peaks == []
        assert r.peak_ratio < 5.0
        assert "No isolated spectral peaks" in r.observation


def test_pure_noise_has_no_peaks() -> None:
    noise = Image.fromarray(
        np.random.default_rng(3).integers(0, 256, (700, 900, 3), dtype=np.uint8), "RGB"
    )
    assert resampling.analyze_resampling(png(noise)).detected is False


def test_upscaled_image_shows_peaks_at_the_expected_frequency() -> None:
    up = SRC.resize((1350, 1050), Image.Resampling.BILINEAR)  # 1.5x -> period 3 px -> f = 1/3
    r = resampling.analyze_resampling(png(up))
    assert r.detected and r.peaks
    strongest = r.peaks[0]
    assert strongest.ratio > 20
    assert any(abs(abs(p.fx) - 1 / 3) < 0.01 or abs(abs(p.fy) - 1 / 3) < 0.01 for p in r.peaks)
    assert "rescaled or rotated" in r.observation


def test_upscale_survives_jpeg_and_other_kernels() -> None:
    bicubic = SRC.resize((1080, 840), Image.Resampling.BICUBIC)  # 1.2x
    assert resampling.analyze_resampling(jpg(bicubic, 80)).detected
    lanczos = SRC.resize((1350, 1050), Image.Resampling.LANCZOS)
    assert resampling.analyze_resampling(jpg(lanczos, 80)).detected


def test_rotation_shows_peaks() -> None:
    rot = SRC.rotate(5, resample=Image.Resampling.BILINEAR)
    assert resampling.analyze_resampling(png(rot)).detected


def test_jpeg_blocking_is_not_reported_as_resampling() -> None:
    # Heavily blocked JPEG of an unresampled picture: 1/8 multiples are masked.
    r = resampling.analyze_resampling(jpg(SRC, 20))
    assert r.detected is False
    for p in r.peaks:
        assert min(abs(abs(p.fx) - k / 8) for k in range(1, 5)) > 0.012


def test_small_image_is_not_measured() -> None:
    r = resampling.analyze_resampling(png(natural((100, 90))))
    assert r.measured is False and r.detected is False and r.tiles == 0
    assert "too small" in r.observation


def test_threshold_is_a_parameter_and_json_shape() -> None:
    up = SRC.resize((1350, 1050), Image.Resampling.BILINEAR)
    r = resampling.analyze_resampling(png(up), min_peak_ratio=1000.0)
    assert r.detected is False
    j = r.to_json()
    assert j["method"] == "resampling" and j["applicable"] is True
    assert set(j) >= {"measured", "peaks", "detected", "observation", "confidence", "limitations"}
    assert j["confidence"] == "low" and j["limitations"] == resampling.LIMITATIONS


async def test_upload_runs_resampling_and_exposes_findings(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await auth_headers(client)
    # Test settings cap uploads at 1 MB, so use a JPEG (the trace survives quality 90).
    up = SRC.resize((1350, 1050), Image.Resampling.BILINEAR)
    r = await client.post(
        "/analysis/image", headers=headers, files={"file": ("up.jpg", jpg(up, 90), "image/jpeg")}
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    body = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    step = next(s for s in body["steps"] if s["name"] == "resampling")
    assert step["status"] == "completed" and step["details"]["detected"] is True
    f = (await client.get(f"/analysis/{aid}/forensics", headers=headers)).json()
    rs = f["resampling"]
    assert rs["method"] == "resampling" and rs["detected"] is True and rs["peaks"]
    assert rs["confidence"] == "low" and rs["limitations"]
    # Shares the row with the other methods.
    assert f["compression"] is not None
