"""Error Level Analysis (ELA). Pure, deterministic; no I/O beyond in-memory encoding.

ELA re-saves a JPEG at a known quality and looks at how much every pixel changed.
Areas that were compressed a different number of times (or at a different
quality) than the rest of the picture tend to re-compress differently, so
localised bright patches *can* indicate a pasted region or local edit.

It is a heuristic with well-known failure modes: high-contrast edges, text,
saturated colours, smooth gradients, chroma subsampling and any full-image
resave all produce error-level differences without any tampering, and a
careful edit re-saved at the original quality can vanish entirely. Results
are reported as POSSIBLE at most and never on their own as manipulation.
"""

import io
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from app.services.image.regions import Region, connected_regions

ELA_VERSION = "v1"
METHOD = "ela"

# Observations are only meaningful for lossy JPEG sources.
APPLICABLE_FORMATS = frozenset({"JPEG"})

# Blocks whose mean error is below this (0..255) are never outliers, whatever the
# statistics say: it stops flat images with near-zero variance from lighting up.
MIN_OUTLIER_LEVEL = 4.0
# A region needs at least this many connected outlier blocks to be reported.
MIN_REGION_BLOCKS = 2
MAX_REGIONS = 8

LIMITATIONS = [
    "ELA is a heuristic. Bright areas show where re-compression changed pixels most; that "
    "happens at sharp edges, text, saturated colours and noise as well as at edits.",
    "A whole-image resave, screenshot or format conversion raises or flattens the error level "
    "everywhere and hides local history. Absence of a pattern is not evidence of no editing.",
    "An edit re-saved at the same JPEG quality as the original can leave no ELA trace.",
    "Only the first frame is analysed, at most at the configured working size; downscaling "
    "blurs block boundaries and weakens the signal.",
]

NOT_APPLICABLE_REASON = (
    "ELA depends on JPEG re-compression behaviour; this file is not a JPEG, so the method "
    "has no interpretable output."
)


@dataclass(frozen=True)
class ELAResult:
    quality: int
    original_width: int
    original_height: int
    working_width: int
    working_height: int
    downscaled: bool
    mean_error: float
    std_error: float
    p95_error: float
    max_error: float
    block_size: int
    outlier_sigma: float
    outlier_block_fraction: float
    regions: list[Region]
    anomaly: bool
    observation: str
    # The amplified difference map, PNG-encoded (working size). Never contains the original.
    visualization_png: bytes = field(repr=False)
    limitations: list[str] = field(default_factory=lambda: list(LIMITATIONS))
    confidence: str = "low"

    def to_json(self) -> dict[str, Any]:
        """Structured observation persisted with the analysis (no image bytes)."""
        return {
            "method": METHOD,
            "version": ELA_VERSION,
            "applicable": True,
            "quality": self.quality,
            "original_width": self.original_width,
            "original_height": self.original_height,
            "working_width": self.working_width,
            "working_height": self.working_height,
            "downscaled": self.downscaled,
            "mean_error": self.mean_error,
            "std_error": self.std_error,
            "p95_error": self.p95_error,
            "max_error": self.max_error,
            "block_size": self.block_size,
            "outlier_sigma": self.outlier_sigma,
            "outlier_block_fraction": self.outlier_block_fraction,
            "regions": [r.to_json("mean_error") for r in self.regions],
            "anomaly": self.anomaly,
            "confidence": self.confidence,
            "observation": self.observation,
            "limitations": list(self.limitations),
        }


def not_applicable_json(pil_format: str) -> dict[str, Any]:
    return {
        "method": METHOD,
        "version": ELA_VERSION,
        "applicable": False,
        "format": pil_format,
        "reason": NOT_APPLICABLE_REASON,
        "limitations": list(LIMITATIONS),
    }


# -- computation -------------------------------------------------------------------------------


def _load_rgb(data: bytes, max_side: int) -> tuple[Image.Image, int, int, bool]:
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        ow, oh = img.size
        rgb = img.convert("RGB")
    downscaled = False
    if max(ow, oh) > max_side:
        scale = max_side / max(ow, oh)
        rgb = rgb.resize(
            (max(1, round(ow * scale)), max(1, round(oh * scale))), Image.Resampling.LANCZOS
        )
        downscaled = True
    return rgb, ow, oh, downscaled


def _resave(rgb: Image.Image, quality: int) -> Image.Image:
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    with Image.open(buf) as again:
        again.load()
        return again.convert("RGB")


def _block_means(err: NDArray[np.float32], block: int) -> NDArray[np.float32]:
    h, w = err.shape
    bh, bw = -(-h // block), -(-w // block)  # ceil
    padded = np.zeros((bh * block, bw * block), dtype=np.float32)
    padded[:h, :w] = err
    # Padding is zero; divide by the real pixel count per block so edge blocks are not diluted.
    sums = padded.reshape(bh, block, bw, block).sum(axis=(1, 3))
    counts = np.zeros_like(sums)
    ones = np.zeros_like(padded)
    ones[:h, :w] = 1
    counts = ones.reshape(bh, block, bw, block).sum(axis=(1, 3))
    return np.asarray(sums / np.maximum(counts, 1), dtype=np.float32)


def _observation(
    *, anomaly: bool, fraction: float, regions: int, mean_error: float, downscaled: bool
) -> str:
    if anomaly:
        text = (
            f"{regions} localised region(s) re-compress with a markedly higher error level than "
            f"the rest of the image ({fraction * 100:.1f}% of blocks). This pattern can arise from "
            "a pasted or locally edited area, but also from sharp detail, text or saturated colour."
        )
    elif mean_error < 1.5:
        text = (
            f"The image changes very little on re-compression (mean error {mean_error:.2f}/255), "
            "which is typical of a file already saved at a similar or lower JPEG quality. ELA has "
            "little discriminating power here."
        )
    elif fraction == 0:
        text = "Error levels are broadly uniform across the image; no localised pattern stands out."
    else:
        text = (
            f"Higher error levels occur but are spread across the image ({fraction * 100:.1f}% of "
            "blocks, no compact region). This is consistent with detail-rich content or a "
            "whole-image resave rather than a local edit."
        )
    if downscaled:
        text += " The image was downscaled before analysis, which weakens the signal."
    return text


def compute_ela(
    data: bytes,
    *,
    quality: int = 95,
    max_side: int = 3000,
    block_size: int = 16,
    outlier_sigma: float = 2.5,
    anomaly_min_fraction: float = 0.005,
    anomaly_max_fraction: float = 0.2,
) -> ELAResult:
    """Run ELA on JPEG bytes. Callers check applicability (format) first."""
    rgb, ow, oh, downscaled = _load_rgb(data, max_side)
    resaved = _resave(rgb, quality)
    a = np.asarray(rgb, dtype=np.int16)
    b = np.asarray(resaved, dtype=np.int16)
    diff = np.abs(a - b)  # (h, w, 3)
    err = diff.max(axis=2).astype(np.float32)

    mean_error = float(err.mean())
    std_error = float(err.std())
    p95 = float(np.percentile(err, 95))
    max_error = float(err.max())

    means = _block_means(err, block_size)
    mu, sigma = float(means.mean()), float(means.std())
    mask = (means > mu + outlier_sigma * sigma) & (means > MIN_OUTLIER_LEVEL)
    fraction = float(mask.mean()) if mask.size else 0.0

    ww, wh = rgb.size
    regions = connected_regions(
        mask,
        means,
        block=block_size,
        scale_x=ow / ww,
        scale_y=oh / wh,
        min_blocks=MIN_REGION_BLOCKS,
        max_regions=MAX_REGIONS,
    )
    anomaly = anomaly_min_fraction <= fraction <= anomaly_max_fraction and len(regions) > 0

    # Amplified difference map: scale so the 99th percentile is near full brightness.
    p99 = float(np.percentile(err, 99))
    scale = 255.0 / max(p99, 1.0)
    vis = np.clip(diff.astype(np.float32) * scale, 0, 255).astype(np.uint8)
    out = io.BytesIO()
    Image.fromarray(vis, mode="RGB").save(out, format="PNG", optimize=True)

    return ELAResult(
        quality=quality,
        original_width=ow,
        original_height=oh,
        working_width=ww,
        working_height=wh,
        downscaled=downscaled,
        mean_error=round(mean_error, 3),
        std_error=round(std_error, 3),
        p95_error=round(p95, 3),
        max_error=round(max_error, 3),
        block_size=block_size,
        outlier_sigma=outlier_sigma,
        outlier_block_fraction=round(fraction, 5),
        regions=regions,
        anomaly=anomaly,
        observation=_observation(
            anomaly=anomaly,
            fraction=fraction,
            regions=len(regions),
            mean_error=mean_error,
            downscaled=downscaled,
        ),
        visualization_png=out.getvalue(),
    )
