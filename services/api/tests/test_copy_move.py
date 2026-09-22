import io

import numpy as np
from httpx import AsyncClient
from PIL import Image

from app.config import Settings
from app.services.image import copy_move
from tests.test_image_upload import auth_headers


def scene(size: tuple[int, int], seed: int = 1) -> np.ndarray:
    """Gradients plus random blobs and mild noise: textured everywhere, nothing repeats."""
    rng = np.random.default_rng(seed)
    w, h = size
    yy, xx = np.mgrid[0:h, 0:w]
    base = 120 + 50 * np.sin(xx / 41.0) + 40 * np.cos(yy / 29.0) + 25 * np.sin((xx * yy) / 900.0)
    for _ in range(60):
        cx, cy, r = rng.integers(0, w), rng.integers(0, h), rng.integers(8, 40)
        base += 60 * np.exp(-((xx - cx) ** 2 + (yy - cy) ** 2) / (2 * r * r)) * rng.choice([-1, 1])
    return np.asarray(np.clip(base + rng.normal(0, 4, (h, w)), 0, 255).astype(np.uint8))


def png(a: np.ndarray) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(a, "L").convert("RGB").save(buf, format="PNG")
    return buf.getvalue()


def jpg(a: np.ndarray, quality: int) -> bytes:
    buf = io.BytesIO()
    Image.fromarray(a, "L").convert("RGB").save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


SRC = scene((900, 700))


def cloned() -> np.ndarray:
    """120x80 patch from (150, 100) pasted at (600, 400): shift (450, 300), not a multiple of 4."""
    c = SRC.copy()
    c[400:480, 600:720] = SRC[100:180, 150:270]
    return c


# -- pure computation ----------------------------------------------------------------------------


def test_unaltered_image_has_no_duplicates() -> None:
    for data in (png(SRC), jpg(SRC, 75)):
        r = copy_move.analyze_copy_move(data)
        assert r.measured and r.detected is False and r.matches == []
        assert "No translated duplicate" in r.observation


def test_clone_is_found_with_the_right_shift_in_png_and_jpeg() -> None:
    for data in (png(cloned()), jpg(cloned(), 85), jpg(cloned(), 60)):
        r = copy_move.analyze_copy_move(data)
        assert r.detected and r.matches
        m = r.matches[0]
        assert (m.shift_x, m.shift_y) == (450, 300)
        assert 140 <= m.source_x <= 160 and 90 <= m.source_y <= 110
        assert 100 <= m.width <= 130 and 70 <= m.height <= 90
        assert m.target_x == m.source_x + 450 and m.target_y == m.source_y + 300
        assert m.pairs >= 200 and m.density > copy_move.MIN_DENSITY
        assert "reappears displaced by (450, 300)" in r.observation


def test_clone_survives_downscaling_and_coordinates_are_original() -> None:
    big = np.kron(cloned(), np.ones((3, 3), np.uint8))  # 2700 x 2100 -> working copy 1024 wide
    r = copy_move.analyze_copy_move(png(big))
    assert r.downscaled and r.working_width == 1024
    assert r.detected
    m = r.matches[0]
    assert abs(m.shift_x - 1350) <= 8 and abs(m.shift_y - 900) <= 8
    assert abs(m.source_x - 450) <= 12 and abs(m.source_y - 300) <= 12


def test_flat_and_noise_images_produce_nothing() -> None:
    flat = np.full((700, 900), 128, np.uint8)
    r = copy_move.analyze_copy_move(png(flat))
    assert r.blocks_textured == 0 and r.detected is False
    noise = np.random.default_rng(3).integers(0, 256, (700, 900), dtype=np.uint8)
    assert copy_move.analyze_copy_move(png(noise)).detected is False


def test_repeating_pattern_is_reported_as_duplicate() -> None:
    # Legitimate repetition trips the method by design; the limitation says so.
    tile = np.tile(SRC[0:64, 0:64], (11, 15))[:700, :900]
    r = copy_move.analyze_copy_move(png(tile))
    assert r.detected and r.matches[0].shift_y == 0 and r.matches[0].shift_x % 64 == 0
    assert any("Repeated real content" in note for note in copy_move.LIMITATIONS)


def test_small_image_is_not_measured() -> None:
    r = copy_move.analyze_copy_move(png(scene((80, 60))))
    assert r.measured is False and r.detected is False


def test_mask_marks_source_and_target() -> None:
    r = copy_move.analyze_copy_move(png(cloned()))
    with Image.open(io.BytesIO(r.visualization_png)) as vis:
        assert vis.format == "PNG" and vis.size == (900, 700)
        arr = np.asarray(vis)
    assert arr[140, 210] == 128  # inside the source patch
    assert arr[440, 660] == 255  # inside the pasted copy
    assert arr[600, 100] == 0  # elsewhere


def test_thresholds_are_parameters_and_json_shape() -> None:
    data = png(cloned())
    assert copy_move.analyze_copy_move(data, min_matches=100_000).detected is False
    assert copy_move.analyze_copy_move(data, min_shift=1000).detected is False
    j = copy_move.analyze_copy_move(data).to_json()
    assert j["method"] == "copy_move" and j["applicable"] is True and j["confidence"] == "low"
    assert "visualization_png" not in j and j["matches"][0]["shift_x"] == 450
    assert j["limitations"] == copy_move.LIMITATIONS


# -- pipeline + API ------------------------------------------------------------------------------


async def test_upload_runs_copy_move_and_exposes_findings_and_mask(
    client: AsyncClient, migrated_settings: Settings
) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("clone.jpg", jpg(cloned(), 90), "image/jpeg")},
    )
    assert r.status_code == 201, r.text
    aid = r.json()["id"]
    body = (await client.get(f"/analysis/{aid}", headers=headers)).json()
    step = next(s for s in body["steps"] if s["name"] == "copy_move")
    assert step["status"] == "completed" and step["details"]["artifact"] == "copy_move.png"
    f = (await client.get(f"/analysis/{aid}/forensics", headers=headers)).json()
    cm = f["copy_move"]
    assert cm["method"] == "copy_move" and cm["detected"] is True
    assert cm["matches"][0]["shift_x"] == 450 and cm["confidence"] == "low"
    arts = {a["method"]: a for a in f["artifacts"]}
    assert {"ela", "noise", "copy_move"} <= set(arts)
    png_resp = await client.get(arts["copy_move"]["url"])
    assert png_resp.status_code == 200 and png_resp.headers["content-type"].startswith("image/png")
