"""Noise consistency. Pure, deterministic; no I/O beyond in-memory PNG encoding.

Sensor noise is roughly uniform across a single capture at a given exposure, and
every later step (compression, denoising, resizing) transforms it globally. A
region pasted from another photo, a different ISO, or a synthetically smoothed
patch therefore tends to carry a *different* noise level from its surroundings.

We estimate the noise standard deviation per block from a high-pass residual
with a robust (median absolute deviation) estimator, keep only *smooth* blocks
so texture is not mistaken for noise, and look for compact clusters whose
level departs from the image's baseline. A cluster is a POSSIBLE signal at
most: sky vs. foliage, bokeh vs. sharp subject, and local denoising by phone
cameras all produce legitimate noise differences.
"""

import io
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from app.services.image.regions import Region, connected_regions

NOISE_VERSION = "v1"
METHOD = "noise"

MIN_SIDE = 64
MIN_REGION_BLOCKS = 2
MAX_REGIONS = 8
# Residual of I - mean(4 neighbours) on iid noise has sigma * sqrt(1 + 4/16).
_RESIDUAL_GAIN = float(np.sqrt(1.25))
_MAD_TO_SIGMA = 1.4826
# Absolute floor for a level difference to count (grey levels); below this it is rounding.
MIN_SIGMA_DIFF = 1.0
SMOOTH_PERCENTILE = 70

LIMITATIONS = [
    "Noise differences are a heuristic. Sky versus foliage, out-of-focus versus sharp areas, "
    "and local denoising by camera pipelines all change the noise level without any editing.",
    "Only smooth blocks are compared; a region pasted into a textured area is not assessed.",
    "Strong JPEG compression flattens noise everywhere and hides differences; very clean "
    "renders or screenshots have no noise to compare.",
    "Regions are reported in block units and may include some surrounding pixels.",
]


@dataclass(frozen=True)
class NoiseResult:
    measured: bool
    width: int
    height: int
    block_size: int
    blocks_total: int
    blocks_smooth: int
    baseline_sigma: float
    spread_sigma: float  # interquartile range across smooth blocks
    outlier_fraction: float
    regions: list[Region]
    anomaly: bool
    observation: str
    visualization_png: bytes = field(repr=False, default=b"")
    confidence: str = "low"

    def to_json(self) -> dict[str, Any]:
        return {
            "method": METHOD,
            "version": NOISE_VERSION,
            "applicable": True,
            "measured": self.measured,
            "width": self.width,
            "height": self.height,
            "block_size": self.block_size,
            "blocks_total": self.blocks_total,
            "blocks_smooth": self.blocks_smooth,
            "baseline_sigma": self.baseline_sigma,
            "spread_sigma": self.spread_sigma,
            "outlier_fraction": self.outlier_fraction,
            "regions": [r.to_json("sigma") for r in self.regions],
            "anomaly": self.anomaly,
            "confidence": self.confidence,
            "observation": self.observation,
            "limitations": list(LIMITATIONS),
        }


# -- estimation ---------------------------------------------------------------------------------


def _residual(gray: NDArray[np.int16]) -> NDArray[np.float32]:
    """I - mean of the 4 neighbours, valid interior only. Float so the MAD is not quantised."""
    core = gray[1:-1, 1:-1]
    nb = gray[:-2, 1:-1] + gray[2:, 1:-1] + gray[1:-1, :-2] + gray[1:-1, 2:]
    return (core.astype(np.float32) - nb.astype(np.float32) / 4.0).astype(np.float32)


def _texture(gray: NDArray[np.int16], block: int) -> NDArray[np.float32]:
    """Per-block texture from an 8x-downsampled image, so pixel noise does not count as texture."""
    h, w = gray.shape
    f = 8
    sh, sw = h // f, w // f
    small = gray[: sh * f, : sw * f].reshape(sh, f, sw, f).mean(axis=(1, 3), dtype=np.float32)
    gx = np.abs(np.diff(small, axis=1))
    gy = np.abs(np.diff(small, axis=0))
    g = gx[:-1, :] + gy[:, :-1]
    sb = max(block // f, 1)
    bh, bw = g.shape[0] // sb, g.shape[1] // sb
    view = g[: bh * sb, : bw * sb].reshape(bh, sb, bw, sb)
    return np.asarray(view.mean(axis=(1, 3)), dtype=np.float32)


def _block_stat(arr: NDArray[Any], block: int, fn: Any) -> NDArray[np.float32]:
    h, w = arr.shape
    bh, bw = h // block, w // block
    view = arr[: bh * block, : bw * block].reshape(bh, block, bw, block).swapaxes(1, 2)
    return np.asarray(fn(view.reshape(bh, bw, block * block), axis=2), dtype=np.float32)


def _mad(a: NDArray[Any], axis: int) -> NDArray[np.float32]:
    med = np.median(a, axis=axis, keepdims=True)
    return np.asarray(np.median(np.abs(a - med), axis=axis), dtype=np.float32)


def _observation(
    *, measured: bool, anomaly: bool, regions: list[Region], baseline: float, smooth: int
) -> str:
    if not measured:
        return "The image is too small for a block-wise noise measurement."
    if smooth == 0:
        return (
            "No smooth blocks were found, so noise levels could not be compared "
            "(the picture is textured everywhere)."
        )
    if anomaly:
        higher = sum(1 for r in regions if r.value > baseline)
        lower = len(regions) - higher
        kinds = []
        if higher:
            kinds.append(f"{higher} noisier")
        if lower:
            kinds.append(f"{lower} smoother")
        return (
            f"Estimated noise is about {baseline:.1f} grey levels across smooth areas, but "
            f"{' and '.join(kinds)} compact region(s) depart from that baseline. This can "
            "come from a pasted or locally processed area, and equally from depth of field, "
            "sky versus foliage, or in-camera denoising."
        )
    return (
        f"Estimated noise is about {baseline:.1f} grey levels and consistent across smooth "
        "areas; no compact region stands out."
    )


def analyze_noise(
    data: bytes,
    *,
    block_size: int = 32,
    outlier_k: float = 3.0,
    anomaly_min_fraction: float = 0.005,
    anomaly_max_fraction: float = 0.25,
) -> NoiseResult:
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        gray = np.asarray(img.convert("L"), dtype=np.int16)
    h, w = gray.shape
    if h < MIN_SIDE or w < MIN_SIDE or h < block_size * 2 or w < block_size * 2:
        return NoiseResult(
            False, w, h, block_size, 0, 0, 0.0, 0.0, 0.0, [], False,
            _observation(measured=False, anomaly=False, regions=[], baseline=0.0, smooth=0),
        )  # fmt: skip

    res = _residual(gray)
    # Per-block noise sigma from the residual MAD; per-block texture from the local gradient.
    sigma = _block_stat(res, block_size, _mad) * _MAD_TO_SIGMA / _RESIDUAL_GAIN
    bh, bw = sigma.shape
    texture = _texture(gray, block_size)
    th, tw = min(bh, texture.shape[0]), min(bw, texture.shape[1])
    sigma, texture = sigma[:th, :tw], texture[:th, :tw]
    bh, bw = sigma.shape

    # Smooth = the least textured 70% of blocks (content-relative, noise-blind).
    smooth = texture <= np.percentile(texture, SMOOTH_PERCENTILE)
    n_smooth = int(smooth.sum())
    if n_smooth < 4:
        return NoiseResult(
            True, w, h, block_size, bh * bw, n_smooth, 0.0, 0.0, 0.0, [], False,
            _observation(measured=True, anomaly=False, regions=[], baseline=0.0, smooth=0),
            visualization_png=_render(sigma, block_size),
        )  # fmt: skip

    levels = sigma[smooth]
    baseline = float(np.median(levels))
    q1, q3 = np.percentile(levels, [25, 75])
    spread = float(q3 - q1)
    # Absolute and relative floors stop near-noiseless renders from flagging rounding effects.
    threshold = max(outlier_k * spread, MIN_SIGMA_DIFF, 0.5 * baseline)
    outliers = smooth & (np.abs(sigma - baseline) > threshold)
    fraction = float(outliers.sum() / max(n_smooth, 1))
    regions = connected_regions(
        outliers, sigma, block=block_size, min_blocks=MIN_REGION_BLOCKS, max_regions=MAX_REGIONS
    )
    anomaly = anomaly_min_fraction <= fraction <= anomaly_max_fraction and len(regions) > 0

    return NoiseResult(
        measured=True,
        width=w,
        height=h,
        block_size=block_size,
        blocks_total=bh * bw,
        blocks_smooth=n_smooth,
        baseline_sigma=round(baseline, 3),
        spread_sigma=round(spread, 3),
        outlier_fraction=round(fraction, 5),
        regions=regions,
        anomaly=anomaly,
        observation=_observation(
            measured=True, anomaly=anomaly, regions=regions, baseline=baseline, smooth=n_smooth
        ),
        visualization_png=_render(sigma, block_size),
    )


def _render(sigma: NDArray[np.float32], block: int) -> bytes:
    """Block-level noise map, one block = ``block`` px, scaled so the 99th percentile is white."""
    p99 = float(np.percentile(sigma, 99)) if sigma.size else 1.0
    scaled = np.clip(sigma / max(p99, 1e-3) * 255.0, 0, 255).astype(np.uint8)
    img = Image.fromarray(scaled, mode="L")
    img = img.resize((scaled.shape[1] * block, scaled.shape[0] * block), Image.Resampling.NEAREST)
    out = io.BytesIO()
    img.save(out, format="PNG", optimize=True)
    return out.getvalue()
