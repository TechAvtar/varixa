import io

import numpy as np
from httpx import AsyncClient
from PIL import Image

from app.config import Settings
from app.services.image import noise
from tests.test_image_upload import auth_headers


def scene(size: tuple[int, int], sigma: float, seed: int = 1) -> np.ndarray:
    """Smooth gradients, a strongly textured band across the middle, Gaussian noise."""
    rng = np.random.default_rng(seed)
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    base = 120 + 50 * np.sin(xx / 90.0) + 40 * np.cos(yy / 70.0)
    band = slice(h // 2 - 40, h // 2 + 40)
    base[band, :] += 40 * np.sign(np.sin(xx[band, :] / 3.0))
    return np.asarray(np.clip(base + rng.normal(0, sigma, (h, w)), 0, 255))


def to_img(a: np.ndarray) -> Image.Image:
    return Image.fromarray(a.astype(np.uint8), "L").convert("RGB")


def png(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def jpg(img: Image.Image, quality: int) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def noisy_patch() -> np.ndarray:
    base = scene((800, 600), 3)
    rng = np.random.default_rng(5)
    patch = scene((800, 600), 0, 2)[80:200, 500:700] + rng.normal(0, 18, (120, 200))
    base[80:200, 500:700] = np.clip(patch, 0, 255)
    return base


def smoothed_patch() -> np.ndarray:
    base = scene((800, 600), 12)
    base[380:520, 100:300] = scene((800, 600), 0.5, 3)[380:520, 100:300]
    return base


# -- pure computation ----------------------------------------------------------------------------


def test_uniform_noise_is_consistent_in_png_and_jpeg() -> None:
    img = to_img(scene((800, 600), 3))
    for data in (png(img), jpg(img, 85), jpg(img, 60)):
        r = noise.analyze_noise(data)
        assert r.measured and r.blocks_smooth > 0
        assert r.anomaly is False and r.regions == [] and r.outlier_fraction == 0.0
        assert "consistent" in r.observation
    r = noise.analyze_noise(png(img))
    assert 2.5 < r.baseline_sigma < 3.5  # recovers the injected sigma


def test_noisier_patch_is_localised() -> None:
    for data in (png(to_img(noisy_patch())), jpg(to_img(noisy_patch()), 85)):
        r = noise.analyze_noise(data)
        assert r.anomaly is True and r.regions
        top = r.regions[0]
        assert top.value > r.baseline_sigma
        # Patch occupies x 500-700, y 80-200; the region must lie inside/overlap it.
        assert 480 <= top.x <= 620 and 40 <= top.y <= 160
        assert "noisier" in r.observation


def test_smoothed_patch_is_localised() -> None:
    for data in (png(to_img(smoothed_patch())), jpg(to_img(smoothed_patch()), 80)):
        r = noise.analyze_noise(data)
        assert r.anomaly is True and r.regions
        top = r.regions[0]
        assert top.value < r.baseline_sigma
        assert 64 <= top.x <= 140 and 350 <= top.y <= 420
        assert "smoother" in r.observation


def test_noiseless_render_and_pure_noise_are_not_flagged() -> None:
    render = noise.analyze_noise(png(to_img(scene((800, 600), 0))))
    assert render.anomaly is False and render.baseline_sigma < 1.0
    pure = Image.fromarray(np.random.default_rng(3).integers(0, 256, (600, 800, 3), dtype=np.uint8))
    assert noise.analyze_noise(png(pure)).anomaly is False


def test_small_image_is_not_measured() -> None:
    r = noise.analyze_noise(png(to_img(scene((50, 50), 3))))
    assert r.measured is False and r.anomaly is False and r.visualization_png == b""
    assert "too small" in r.observation


def test_visualization_is_block_map_png() -> None:
    r = noise.analyze_noise(png(to_img(scene((800, 600), 3))))
    with Image.open(io.BytesIO(r.visualization_png)) as vis:
        assert vis.format == "PNG" and vis.mode == "L"
        assert vis.size[0] % r.block_size == 0 and vis.size[1] % r.block_size == 0
        assert vis.size[0] <= 800 and vis.size[1] <= 600


def test_thresholds_are_parameters_and_json_shape() -> None:
    data = png(to_img(noisy_patch()))
    # The absolute/relative floors still apply, so use the fraction band to switch it off.
    assert noise.analyze_noise(data, anomaly_min_fraction=0.9).anomaly is False
    assert noise.analyze_noise(data, anomaly_max_fraction=0.0).anomaly is False
    j = noise.analyze_noise(data).to_json()
    assert j["method"] == "noise" and j["applicable"] is True and j["confidence"] == "low"
    assert "visualization_png" not in j and j["regions"][0]["sigma"] > 0
    assert j["limitations"] == noise.LIMITATIONS


# -- pipeline + API ------------------------------------------------------------------------------


async def test_upload_runs_noise_and_exposes_findings_and_map(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("n.jpg", jpg(to_img(noisy_patch()), 90), "image/jpeg")},
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    body = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    step = next(s for s in body["steps"] if s["name"] == "noise")
    assert step["status"] == "completed" and step["details"]["artifact"] == "noise.png"
    f = (await client.get(f"/analysis/{aid}/forensics", headers=headers)).json()
    n = f["noise"]
    assert n["method"] == "noise" and n["anomaly"] is True and n["regions"]
    assert n["confidence"] == "low" and n["limitations"]
    arts = {a["method"]: a for a in f["artifacts"]}
    assert "noise" in arts and "ela" in arts  # both maps live in the same artifacts list
    png_resp = await client.get(arts["noise"]["url"])
    assert png_resp.status_code == 200 and png_resp.headers["content-type"].startswith("image/png")
