"""JPEG / compression observations. Pure, deterministic; no I/O.

Two kinds of output, kept apart because they carry different weight:

* **Encoding facts** (JPEG only) read straight from the file: quantisation tables,
  estimated IJG quality, whether the tables are the standard ones, chroma
  subsampling and progressive/baseline mode. These describe the *last* save and
  say nothing about editing by themselves.
* **Block-grid heuristic** (any format): JPEG leaves an 8x8 blocking pattern. If
  that pattern is offset from the file's own block boundaries, the picture was
  most likely cropped or shifted after an earlier JPEG save and saved again. If
  a lossless file (PNG/TIFF) carries the pattern, it was probably a JPEG once.
  Both are low-confidence signals, correlated with ELA, and never proof.
"""

import io
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.typing import NDArray
from PIL import Image, JpegImagePlugin

COMPRESSION_VERSION = "v1"
METHOD = "compression"
BLOCK = 8
MIN_GRID_SIDE = 64  # below this there are too few block boundaries to measure

# Standard IJG tables (Annex K of ITU-T T.81), natural (row-major) order.
STD_LUMA = np.array(
    [
        16, 11, 10, 16, 24, 40, 51, 61,
        12, 12, 14, 19, 26, 58, 60, 55,
        14, 13, 16, 24, 40, 57, 69, 56,
        14, 17, 22, 29, 51, 87, 80, 62,
        18, 22, 37, 56, 68, 109, 103, 77,
        24, 35, 55, 64, 81, 104, 113, 92,
        49, 64, 78, 87, 103, 121, 120, 101,
        72, 92, 95, 98, 112, 100, 103, 99,
    ],
    dtype=np.float64,
)  # fmt: skip
STD_CHROMA = np.array(
    [
        17, 18, 24, 47, 99, 99, 99, 99,
        18, 21, 26, 66, 99, 99, 99, 99,
        24, 26, 56, 99, 99, 99, 99, 99,
        47, 66, 99, 99, 99, 99, 99, 99,
        99, 99, 99, 99, 99, 99, 99, 99,
        99, 99, 99, 99, 99, 99, 99, 99,
        99, 99, 99, 99, 99, 99, 99, 99,
        99, 99, 99, 99, 99, 99, 99, 99,
    ],
    dtype=np.float64,
)  # fmt: skip

SUBSAMPLING = {0: "4:4:4", 1: "4:2:2", 2: "4:2:0"}

LIMITATIONS = [
    "Quantisation tables, quality and subsampling describe only the most recent save. They "
    "identify encoder settings, not whether the content was edited.",
    "The block-grid check is a heuristic: strong texture, noise or scaling can hide or mimic a "
    "grid, and many legitimate workflows (crop and re-save, screenshot of a JPEG) produce an "
    "offset or inherited grid.",
    "Block-grid and ELA observations are correlated; they are not independent evidence.",
    "Lossy WebP uses its own block structure, so a weak 8-pixel grid in a WebP file is expected.",
]


@dataclass(frozen=True)
class EncodingFacts:
    """Read directly from the JPEG headers."""

    progressive: bool
    subsampling: str | None
    table_count: int
    estimated_quality: int | None
    standard_tables: bool
    luma_table_error: float | None
    chroma_estimated_quality: int | None
    has_jfif: bool
    has_adobe: bool

    def to_json(self) -> dict[str, Any]:
        return {
            "progressive": self.progressive,
            "subsampling": self.subsampling,
            "table_count": self.table_count,
            "estimated_quality": self.estimated_quality,
            "standard_tables": self.standard_tables,
            "luma_table_error": self.luma_table_error,
            "chroma_estimated_quality": self.chroma_estimated_quality,
            "has_jfif": self.has_jfif,
            "has_adobe": self.has_adobe,
        }


@dataclass(frozen=True)
class BlockGrid:
    """8-pixel periodicity of pixel differences, per phase 0..7, in each direction."""

    measured: bool
    aligned_strength: float
    offset_x: int
    offset_y: int
    offset_strength: float
    detected_aligned: bool
    detected_offset: bool
    profile_x: list[float]
    profile_y: list[float]

    def to_json(self) -> dict[str, Any]:
        return {
            "measured": self.measured,
            "aligned_strength": self.aligned_strength,
            "offset_x": self.offset_x,
            "offset_y": self.offset_y,
            "offset_strength": self.offset_strength,
            "detected_aligned": self.detected_aligned,
            "detected_offset": self.detected_offset,
            "profile_x": self.profile_x,
            "profile_y": self.profile_y,
        }


@dataclass(frozen=True)
class CompressionResult:
    format: str
    lossless_container: bool
    encoding: EncodingFacts | None
    grid: BlockGrid
    anomaly: bool
    prior_jpeg_grid: bool
    observation: str
    confidence: str = "low"

    def to_json(self) -> dict[str, Any]:
        return {
            "method": METHOD,
            "version": COMPRESSION_VERSION,
            "applicable": True,
            "format": self.format,
            "lossless_container": self.lossless_container,
            "encoding": self.encoding.to_json() if self.encoding else None,
            "grid": self.grid.to_json(),
            "anomaly": self.anomaly,
            "prior_jpeg_grid": self.prior_jpeg_grid,
            "confidence": self.confidence,
            "observation": self.observation,
            "limitations": list(LIMITATIONS),
        }


# -- encoding facts -----------------------------------------------------------------------------


def _scaled_table(std: NDArray[np.float64], quality: int) -> NDArray[np.float64]:
    q = min(max(quality, 1), 100)
    scale = 5000 // q if q < 50 else 200 - 2 * q  # libjpeg uses integer division
    return np.clip(np.floor((std * scale + 50) / 100), 1, 255)


def estimate_quality(table: list[int], std: NDArray[np.float64]) -> tuple[int, float]:
    """Closest IJG quality for a table and the mean absolute deviation from that standard table."""
    observed = np.asarray(table, dtype=np.float64)
    if observed.shape != (64,):
        return 0, float("inf")
    best_q, best_err = 0, float("inf")
    for q in range(1, 101):
        err = float(np.abs(_scaled_table(std, q) - observed).mean())
        if err < best_err:
            best_q, best_err = q, err
    return best_q, best_err


def read_encoding(img: Image.Image) -> EncodingFacts:
    tables: dict[int, list[int]] = dict(getattr(img, "quantization", None) or {})
    luma = tables.get(0)
    chroma = tables.get(1)
    est_q: int | None = None
    luma_err: float | None = None
    chroma_q: int | None = None
    if luma:
        est_q, luma_err = estimate_quality(list(luma), STD_LUMA)
    if chroma:
        chroma_q, _ = estimate_quality(list(chroma), STD_CHROMA)
    sampling = JpegImagePlugin.get_sampling(img)
    return EncodingFacts(
        progressive=bool(img.info.get("progressive") or img.info.get("progression")),
        subsampling=SUBSAMPLING.get(sampling),
        table_count=len(tables),
        estimated_quality=est_q,
        standard_tables=luma_err is not None and luma_err == 0.0,
        luma_table_error=round(luma_err, 3) if luma_err is not None else None,
        chroma_estimated_quality=chroma_q,
        has_jfif="jfif" in img.info,
        has_adobe="adobe" in img.info,
    )


# -- block grid ---------------------------------------------------------------------------------


def _phase_profile(diff: NDArray[np.float32], axis: int) -> list[float]:
    """Mean absolute difference at each position mod 8 along ``axis`` (0 = rows/y, 1 = cols/x).

    ``diff`` at index i is |I[i] - I[i-1]|, so a block boundary between 7|8 lands at phase 0.
    """
    n = diff.shape[axis]
    idx = np.arange(1, n + 1) % BLOCK  # diff index i corresponds to pixel i+1
    profile = []
    for phase in range(BLOCK):
        sel = np.take(diff, np.nonzero(idx == phase)[0], axis=axis)
        profile.append(float(sel.mean()) if sel.size else 0.0)
    return profile


def _strength(profile: list[float], phase: int) -> float:
    others = [v for i, v in enumerate(profile) if i != phase]
    base = float(np.median(others)) if others else 0.0
    return (profile[phase] / base - 1.0) if base > 0 else 0.0


def measure_grid(gray: NDArray[np.uint8], *, min_strength: float) -> BlockGrid:
    h, w = gray.shape
    if h < MIN_GRID_SIDE or w < MIN_GRID_SIDE:
        return BlockGrid(False, 0.0, 0, 0, 0.0, False, False, [], [])
    g = gray.astype(np.int16)
    dx = np.abs(np.diff(g, axis=1)).astype(np.float32)  # (h, w-1)
    dy = np.abs(np.diff(g, axis=0)).astype(np.float32)  # (h-1, w)
    px = _phase_profile(dx, axis=1)
    py = _phase_profile(dy, axis=0)
    aligned = min(_strength(px, 0), _strength(py, 0))

    # Strongest phase other than 0 in each direction; an offset grid needs both directions
    # and must be at least half as strong as the aligned grid, because the phases next to a
    # strong aligned boundary are raised by spill-over.
    sx = [(_strength(px, k), k) for k in range(1, BLOCK)]
    sy = [(_strength(py, k), k) for k in range(1, BLOCK)]
    (stx, kx), (sty, ky) = max(sx), max(sy)
    offset_strength = min(stx, sty)
    return BlockGrid(
        measured=True,
        aligned_strength=round(aligned, 4),
        offset_x=kx,
        offset_y=ky,
        offset_strength=round(offset_strength, 4),
        detected_aligned=aligned >= min_strength,
        detected_offset=offset_strength >= min_strength
        and offset_strength >= 0.5 * max(aligned, 0.0),
        profile_x=[round(v, 4) for v in px],
        profile_y=[round(v, 4) for v in py],
    )


# -- assembly -----------------------------------------------------------------------------------

LOSSLESS_FORMATS = frozenset({"PNG", "TIFF", "BMP", "GIF"})


def _observation(fmt: str, enc: EncodingFacts | None, grid: BlockGrid) -> str:
    parts: list[str] = []
    if enc is not None:
        mode = "progressive" if enc.progressive else "baseline"
        sub = enc.subsampling or "unknown"
        if enc.estimated_quality is None:
            tables = "no readable quantisation tables"
        elif enc.standard_tables:
            tables = f"standard IJG tables at quality {enc.estimated_quality}"
        else:
            tables = (
                f"custom quantisation tables (closest standard quality {enc.estimated_quality})"
            )
        parts.append(f"Saved as a {mode} JPEG with {sub} chroma subsampling and {tables}.")
        parts.append(
            "These settings describe the last save only; quality is not evidence of editing."
        )
    elif fmt in LOSSLESS_FORMATS:
        parts.append(f"{fmt} is a lossless container, so there are no JPEG quantisation settings.")
    else:
        parts.append(f"{fmt} does not use JPEG quantisation tables.")

    if not grid.measured:
        parts.append("The image is too small for a block-grid measurement.")
    elif grid.detected_offset and enc is not None:
        parts.append(
            f"A second 8x8 blocking grid offset by ({grid.offset_x}, {grid.offset_y}) px from "
            "the file's block boundaries is detectable. This is consistent with the picture "
            "having been cropped or shifted after an earlier JPEG save and then saved again; it "
            "can also come from repeating texture."
        )
    elif grid.detected_offset or (grid.detected_aligned and enc is None):
        parts.append(
            "An 8x8 JPEG-style blocking grid is detectable although the file is not a JPEG, "
            "which suggests the content was JPEG-compressed at some earlier point."
        )
    elif grid.detected_aligned:
        parts.append(
            "An 8x8 blocking grid aligned with the file's block boundaries is detectable, as "
            "expected for any JPEG; no offset grid stands out."
        )
    else:
        parts.append("No 8x8 blocking grid stands out (high quality, detailed content or scaling).")
    return " ".join(parts)


def analyze_compression(data: bytes, *, grid_min_strength: float = 0.08) -> CompressionResult:
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        fmt = img.format or "UNKNOWN"
        enc = read_encoding(img) if fmt == "JPEG" else None
        gray = np.asarray(img.convert("L"), dtype=np.uint8)
    grid = measure_grid(gray, min_strength=grid_min_strength)
    is_jpeg = enc is not None
    anomaly = is_jpeg and grid.detected_offset
    prior = (not is_jpeg) and (grid.detected_aligned or grid.detected_offset)
    return CompressionResult(
        format=fmt,
        lossless_container=fmt in LOSSLESS_FORMATS,
        encoding=enc,
        grid=grid,
        anomaly=anomaly,
        prior_jpeg_grid=prior,
        observation=_observation(fmt, enc, grid),
    )
