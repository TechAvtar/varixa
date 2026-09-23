"""JPEG double-compression detection (JPEG ghosts). Pure, deterministic; in-memory only.

A JPEG that was compressed before at quality q1 and then saved again at q2 > q1 keeps a
"ghost" of the first compression: re-saving it at q1 changes it *less* than re-saving at
nearby qualities, so the error-versus-quality curve dips at q1 (Farid, 2009). Measured per
block, the dip appears only in the areas that share that history, which is how a region
pasted from another JPEG shows up. A second, independent look at the DC coefficient
histogram (Popescu and Farid) sees the periodic gaps a first quantiser leaves behind.

Heuristic, with known failure modes: re-saving is routine (messaging apps, editors, web
uploads all do it), a first save at *higher* quality than the last is invisible, flat or
heavily textured areas hide ghosts, and any resampling between saves destroys them.
Results are POSSIBLE at most; a whole-image ghost is history, not evidence of editing.
"""

import io
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from app.services.image.compression import read_encoding
from app.services.image.regions import Region, connected_regions

DOUBLE_COMPRESSION_VERSION = "v1"
METHOD = "double_compression"
APPLICABLE_FORMATS = frozenset({"JPEG"})

QUALITIES: tuple[int, ...] = tuple(range(50, 101, 2))
BLOCK = 16
# Local minima are judged against the curve this many samples (4 quality points) either side.
_DEPTH_SPAN = 2
# Samples around the last-save quality that are never candidates for an earlier compression.
_EXCLUDE_SPAN = 3
MIN_REGION_BLOCKS = 3
MAX_REGIONS = 8
_HIST_HALF = 256

LIMITATIONS = [
    "A JPEG ghost shows that pixels were JPEG-compressed before at a lower quality; re-saving "
    "is routine (messaging apps, editors, web uploads) and is not evidence of editing by itself.",
    "An earlier save at a higher quality than the last one leaves no ghost, and resampling or "
    "cropping between saves destroys it. Absence of a ghost says nothing.",
    "Flat areas carry no ghost and heavily textured areas blur it; a pasted region from a "
    "different JPEG is the clearest case, an edit re-saved at the same quality the weakest.",
    "The DC-histogram periodicity check corroborates a whole-image double compression only; "
    "custom quantisation tables can mimic or hide it.",
]

NOT_APPLICABLE_REASON = (
    "JPEG ghosts depend on JPEG quantisation history; this file is not a JPEG, so the method "
    "has no interpretable output."
)


@dataclass(frozen=True)
class DoubleCompressionResult:
    original_width: int
    original_height: int
    working_width: int
    working_height: int
    cropped: bool
    last_quality: int | None
    standard_tables: bool | None
    qualities: list[int]
    curve: list[float]
    primary_quality: int
    secondary_quality: int | None
    secondary_depth: float
    dc_periodicity: float
    dc_period: float | None
    periodic: bool
    block_size: int
    ghost_block_fraction: float
    ghost_quality_local: int | None
    regions: list[Region]
    detected: bool  # whole-image earlier compression at a lower quality
    anomaly: bool  # localised: only part of the image carries the ghost
    observation: str
    visualization_png: bytes = field(repr=False)
    limitations: list[str] = field(default_factory=lambda: list(LIMITATIONS))
    confidence: str = "low"

    def to_json(self) -> dict[str, Any]:
        return {
            "method": METHOD,
            "version": DOUBLE_COMPRESSION_VERSION,
            "applicable": True,
            "original_width": self.original_width,
            "original_height": self.original_height,
            "working_width": self.working_width,
            "working_height": self.working_height,
            "cropped": self.cropped,
            "last_quality": self.last_quality,
            "standard_tables": self.standard_tables,
            "qualities": self.qualities,
            "curve": self.curve,
            "primary_quality": self.primary_quality,
            "secondary_quality": self.secondary_quality,
            "secondary_depth": self.secondary_depth,
            "dc_periodicity": self.dc_periodicity,
            "dc_period": self.dc_period,
            "periodic": self.periodic,
            "block_size": self.block_size,
            "ghost_block_fraction": self.ghost_block_fraction,
            "ghost_quality_local": self.ghost_quality_local,
            "regions": [r.to_json("depth") for r in self.regions],
            "detected": self.detected,
            "anomaly": self.anomaly,
            "confidence": self.confidence,
            "observation": self.observation,
            "limitations": list(self.limitations),
        }


def not_applicable_json(pil_format: str) -> dict[str, Any]:
    return {
        "method": METHOD,
        "version": DOUBLE_COMPRESSION_VERSION,
        "applicable": False,
        "format": pil_format,
        "reason": NOT_APPLICABLE_REASON,
        "limitations": list(LIMITATIONS),
    }


# -- helpers ------------------------------------------------------------------------------------


def _luma(img: Image.Image) -> NDArray[np.float32]:
    return np.asarray(img.convert("L"), dtype=np.float32)


def _resave_luma(rgb: Image.Image, quality: int) -> NDArray[np.float32]:
    buf = io.BytesIO()
    rgb.save(buf, format="JPEG", quality=quality)
    buf.seek(0)
    with Image.open(buf) as again:
        again.load()
        return _luma(again)


def _block_means(err: NDArray[np.float32], block: int) -> NDArray[np.float32]:
    h, w = err.shape
    bh, bw = h // block, w // block  # working image is trimmed to whole blocks
    return err[: bh * block, : bw * block].reshape(bh, block, bw, block).mean(axis=(1, 3))


def _depths(curves: NDArray[np.floating[Any]], exclude: int) -> NDArray[np.floating[Any]]:
    """Dip depth at every quality sample: min of the neighbours at +-span minus the value.

    ``curves`` is (Q, ...) and normalised per position; samples within ``_EXCLUDE_SPAN`` of
    ``exclude`` (the last save) and above it are set to zero, since only an *earlier, lower*
    quality can leave a ghost.
    """
    q = curves.shape[0]
    depth = np.zeros_like(curves)
    for i in range(q):
        lo, hi = max(0, i - _DEPTH_SPAN), min(q - 1, i + _DEPTH_SPAN)
        if lo == i or hi == i:
            continue
        depth[i] = np.minimum(curves[lo], curves[hi]) - curves[i]
    depth[max(0, exclude - _EXCLUDE_SPAN) :] = 0.0
    return np.maximum(depth, 0.0)


def _pick_dip(depth: NDArray[np.floating[Any]], min_depth: float) -> int | None:
    """Index of the earliest (lowest-quality) dip that is at least as deep as the threshold.

    A first compression at q1 also leaves weaker harmonic dips at qualities whose quantiser
    steps divide q1's; the genuine earlier save is the lowest of the strong dips.
    """
    strongest = float(depth.max()) if depth.size else 0.0
    if strongest < min_depth:
        return None
    candidates = np.flatnonzero(depth >= max(min_depth, 0.6 * strongest))
    return int(candidates[0]) if candidates.size else None


def dc_periodicity(luma: NDArray[np.float32], dc_step: int) -> tuple[float, float | None]:
    """Peak-to-median ratio of the DC coefficient histogram's spectrum, and its period.

    After dividing by the current DC quantiser, a single-compressed JPEG has a smooth DC
    histogram; an earlier, coarser quantiser leaves comb-like gaps with a period equal to
    the ratio of the two steps.
    """
    h, w = luma.shape
    bh, bw = h // 8, w // 8
    if bh * bw < 64:
        return 0.0, None
    blocks = luma[: bh * 8, : bw * 8].reshape(bh, 8, bw, 8)
    dc = blocks.sum(axis=(1, 3)) / 8.0 - 128.0 * 8.0  # orthonormal DC of level-shifted block
    k = np.round(dc / max(dc_step, 1)).astype(np.int64).ravel()
    k = k[(k >= -_HIST_HALF) & (k < _HIST_HALF)]
    if k.size < 64:
        return 0.0, None
    hist = np.bincount(k + _HIST_HALF, minlength=2 * _HIST_HALF).astype(np.float64)
    hist -= hist.mean()
    spectrum = np.abs(np.fft.rfft(hist))
    # Ignore the lowest frequencies (envelope) and the Nyquist bin.
    start = 8
    if spectrum.size <= start + 2:
        return 0.0, None
    body = spectrum[start:-1]
    median = float(np.median(body))
    if median <= 1e-9:
        return 0.0, None
    peak_index = int(np.argmax(body)) + start
    ratio = float(body.max() / median)
    period = (2 * _HIST_HALF) / peak_index if peak_index else None
    return round(ratio, 3), round(period, 3) if period else None


def _observation(r: dict[str, Any]) -> str:
    parts: list[str] = []
    if r["anomaly"]:
        parts.append(
            f"{r['regions']} region(s) carry a JPEG ghost at about quality "
            f"{r['ghost_quality_local']} that the rest of the image does not "
            f"({r['ghost_block_fraction'] * 100:.1f}% of blocks). "
            "This is what a region pasted from a lower-quality JPEG looks like; strong texture "
            "boundaries can produce the same pattern."
        )
    elif r["detected"]:
        parts.append(
            f"The whole image carries a JPEG ghost at about quality {r['secondary_quality']} "
            f"(dip depth {r['secondary_depth']:.2f}) beneath the last save at about "
            f"{r['primary_quality']}: it was JPEG-compressed at least twice. Re-saving is routine "
            "and does not indicate editing on its own."
        )
    else:
        parts.append(
            "No JPEG ghost stands out: the error-versus-quality curve dips only at the last save "
            f"(about quality {r['primary_quality']}). An earlier save at higher quality would be "
            "invisible."
        )
    if r["periodic"]:
        parts.append(
            f"The DC-coefficient histogram is periodic (peak ratio {r['dc_periodicity']:.1f}), "
            "which corroborates an earlier, coarser quantisation."
        )
    if r["cropped"]:
        parts.append("Only the central part of the image was analysed (size cap).")
    return " ".join(parts)


# -- entry point --------------------------------------------------------------------------------


def analyze_double_compression(
    data: bytes,
    *,
    max_pixels: int = 2_500_000,
    min_depth: float = 0.12,
    anomaly_min_fraction: float = 0.01,
    anomaly_max_fraction: float = 0.6,
    periodicity_min: float = 5.0,
) -> DoubleCompressionResult:
    """Run the ghost analysis on JPEG bytes. Callers check applicability (format) first."""
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        ow, oh = img.size
        enc = read_encoding(img)
        rgb = img.convert("RGB")
        dc_step = 1
        try:
            tables = getattr(img, "quantization", None) or {}
            dc_step = int(next(iter(tables.values()))[0]) if tables else 1
        except (TypeError, ValueError, IndexError):
            dc_step = 1

    # Never resample (that would destroy the block history); crop the centre instead.
    cropped = False
    if ow * oh > max_pixels:
        scale = (max_pixels / (ow * oh)) ** 0.5
        cw, ch = max(BLOCK, int(ow * scale) // 8 * 8), max(BLOCK, int(oh * scale) // 8 * 8)
        left, top = ((ow - cw) // 2) // 8 * 8, ((oh - ch) // 2) // 8 * 8
        rgb = rgb.crop((left, top, left + cw, top + ch))
        cropped = True
    else:
        left = top = 0
    ww, wh = rgb.size
    original = _luma(rgb)

    qualities = list(QUALITIES)
    stacks = np.stack(
        [_block_means(np.abs(_resave_luma(rgb, q) - original), BLOCK) for q in qualities]
    )  # (Q, bh, bw)
    if stacks.shape[1] == 0 or stacks.shape[2] == 0:
        stacks = np.zeros((len(qualities), 1, 1), dtype=np.float32)
    norm = stacks / np.maximum(stacks.max(axis=0, keepdims=True), 1e-6)
    curve = norm.mean(axis=(1, 2))

    last_q = enc.estimated_quality if enc and enc.standard_tables else None
    if last_q is not None:
        primary_index = int(np.argmin(np.abs(np.asarray(qualities) - last_q)))
    else:
        primary_index = int(np.argmin(curve))
    primary_quality = qualities[primary_index]

    global_depth = _depths(curve[:, None, None], primary_index)[:, 0, 0]
    picked = _pick_dip(global_depth, min_depth)
    secondary_index = picked if picked is not None else int(np.argmax(global_depth))
    secondary_depth = float(global_depth[secondary_index])
    secondary_quality = qualities[secondary_index] if picked is not None else None

    block_depth = _depths(norm, primary_index)  # (Q, bh, bw)
    best_index = block_depth.argmax(axis=0)
    best_depth = block_depth.max(axis=0)
    ghost_mask = best_depth >= min_depth
    fraction = float(ghost_mask.mean()) if ghost_mask.size else 0.0
    ghost_quality_local: int | None = None
    if ghost_mask.any():
        # The quality the ghost blocks agree on: the deepest dip of their mean curve.
        ghost_curve = norm[:, ghost_mask].mean(axis=1)
        ghost_depth = _depths(ghost_curve[:, None, None], primary_index)[:, 0, 0]
        local_pick = _pick_dip(ghost_depth, min_depth)
        ghost_quality_local = qualities[
            local_pick if local_pick is not None else int(np.argmax(ghost_depth))
        ]

    regions = connected_regions(
        ghost_mask,
        best_depth,
        block=BLOCK,
        scale_x=1.0,
        scale_y=1.0,
        min_blocks=MIN_REGION_BLOCKS,
        max_regions=MAX_REGIONS,
    )
    if cropped and regions:  # back to original coordinates
        regions = [
            Region(r.x + left, r.y + top, r.width, r.height, r.blocks, r.value) for r in regions
        ]
    periodicity, period = dc_periodicity(original, dc_step)
    periodic = periodicity >= periodicity_min

    anomaly = (
        anomaly_min_fraction <= fraction <= anomaly_max_fraction
        and len(regions) > 0
        and secondary_quality is None  # a ghost everywhere is history, not a local anomaly
    )
    # Whole-image history: a global dip, ghosts nearly everywhere, or (absent a local
    # anomaly, which also makes the histogram periodic) the DC comb on its own.
    detected = (
        secondary_quality is not None
        or fraction > anomaly_max_fraction
        or (periodic and not anomaly)
    )
    if not anomaly:
        regions = []  # boxes only mean something when the ghost is localised
    del best_index

    vis = np.clip(best_depth / max(float(best_depth.max()), 1e-6) * 255.0, 0, 255).astype(np.uint8)
    vis_img = Image.fromarray(vis, mode="L").resize((ww, wh), Image.Resampling.NEAREST)
    out = io.BytesIO()
    vis_img.convert("RGB").save(out, format="PNG", optimize=True)

    fields: dict[str, Any] = {
        "anomaly": anomaly,
        "detected": detected,
        "regions": len(regions),
        "ghost_quality_local": ghost_quality_local,
        "ghost_block_fraction": fraction,
        "secondary_quality": secondary_quality,
        "secondary_depth": secondary_depth,
        "primary_quality": primary_quality,
        "periodic": periodic,
        "dc_periodicity": periodicity,
        "cropped": cropped,
    }
    return DoubleCompressionResult(
        original_width=ow,
        original_height=oh,
        working_width=ww,
        working_height=wh,
        cropped=cropped,
        last_quality=last_q,
        standard_tables=enc.standard_tables if enc else None,
        qualities=qualities,
        curve=[round(float(v), 4) for v in curve],
        primary_quality=primary_quality,
        secondary_quality=secondary_quality,
        secondary_depth=round(secondary_depth, 4),
        dc_periodicity=periodicity,
        dc_period=period,
        periodic=periodic,
        block_size=BLOCK,
        ghost_block_fraction=round(fraction, 5),
        ghost_quality_local=ghost_quality_local,
        regions=regions,
        detected=detected,
        anomaly=anomaly,
        observation=_observation(fields),
        visualization_png=out.getvalue(),
    )
