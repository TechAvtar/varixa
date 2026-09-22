"""Resampling / interpolation traces. Pure, deterministic; no I/O.

Rescaling or rotating an image interpolates new pixels from old ones, which
leaves *periodic* correlations between neighbouring pixels (Popescu & Farid
2005). Following Kirchner (2008) we compute the residual of a fixed linear
predictor, turn it into a probability-like map and look for isolated peaks in
that map's 2D spectrum. A clean, unresampled capture has no such peaks.

Care points:
* JPEG blocking is itself periodic (every 8 px), so bins at multiples of 1/8
  along either axis are masked before peak search.
* The image is *never* resized before analysis (that would plant the very
  signal we look for). Large images are sampled with fixed-size tiles and the
  spectra are averaged, which strengthens consistent peaks and washes out noise.
* Whole-image resampling is routine (any resize for the web). A detected trace
  says "this picture was rescaled or rotated at some point", not "edited".
  Localised resampling (a pasted, rescaled object) is not attempted here.
"""

import io
from dataclasses import dataclass
from typing import Any

import numpy as np
from numpy.lib.stride_tricks import sliding_window_view
from numpy.typing import NDArray
from PIL import Image

RESAMPLING_VERSION = "v1"
METHOD = "resampling"

TILE = 512
MAX_TILES = 6
MIN_SIDE = 128
NEIGHBOURHOOD = 9  # bins, for the local-background estimate
DC_RADIUS = 0.04  # normalised frequency; DC surroundings are always strong
JPEG_TOLERANCE = 0.012  # mask |f - k/8| below this, k = 1..4
MAX_PEAKS = 6

# Fixed 3x3 predictor (Kirchner): each pixel predicted from its 8 neighbours.
_PREDICTOR = np.array([[-0.25, 0.5, -0.25], [0.5, 0.0, 0.5], [-0.25, 0.5, -0.25]], dtype=np.float32)

LIMITATIONS = [
    "A resampling trace means the picture was rescaled or rotated at some point. Resizing "
    "for the web, thumbnails and camera pipelines do this routinely; it is not evidence of "
    "manipulation.",
    "Only global traces are measured. A pasted object that was rescaled before compositing is "
    "not localised by this method.",
    "Strong JPEG compression, heavy noise, repeating texture (fabric, screens, halftone) and "
    "very smooth content can hide or mimic spectral peaks.",
    "Frequencies at multiples of 1/8 and the Nyquist line are excluded to avoid confusing JPEG "
    "blocking with resampling, so rescaling by exactly 2x (or other factors whose trace falls "
    "there) can go unnoticed.",
    "Downscaling leaves a much weaker trace than upscaling and is often not detected.",
]


@dataclass(frozen=True)
class SpectralPeak:
    fx: float  # normalised frequency, cycles per pixel, in [-0.5, 0.5]
    fy: float
    ratio: float  # peak magnitude / local background

    def to_json(self) -> dict[str, Any]:
        return {"fx": self.fx, "fy": self.fy, "ratio": self.ratio}


@dataclass(frozen=True)
class ResamplingResult:
    measured: bool
    width: int
    height: int
    tiles: int
    tile_size: int
    peak_ratio: float
    peaks: list[SpectralPeak]
    detected: bool
    observation: str
    confidence: str = "low"

    def to_json(self) -> dict[str, Any]:
        return {
            "method": METHOD,
            "version": RESAMPLING_VERSION,
            "applicable": True,
            "measured": self.measured,
            "width": self.width,
            "height": self.height,
            "tiles": self.tiles,
            "tile_size": self.tile_size,
            "peak_ratio": self.peak_ratio,
            "peaks": [p.to_json() for p in self.peaks],
            "detected": self.detected,
            "confidence": self.confidence,
            "observation": self.observation,
            "limitations": list(LIMITATIONS),
        }


# -- core ---------------------------------------------------------------------------------------


def _residual(tile: NDArray[np.float32]) -> NDArray[np.float32]:
    """Prediction residual with the fixed 3x3 predictor (valid region only)."""
    h, w = tile.shape
    pred = np.zeros((h - 2, w - 2), dtype=np.float32)
    for dy in range(3):
        for dx in range(3):
            k = _PREDICTOR[dy, dx]
            if k:
                pred += k * tile[dy : dy + h - 2, dx : dx + w - 2]
    return tile[1 : h - 1, 1 : w - 1] - pred


def _pmap(res: NDArray[np.float32]) -> NDArray[np.float32]:
    """Probability-like map: near 1 where the predictor fits, near 0 where it does not."""
    scale = float(np.median(np.abs(res))) + 1e-3
    return np.exp(-np.abs(res) / scale).astype(np.float32)


def _spectrum(p: NDArray[np.float32]) -> NDArray[np.float32]:
    p = p - p.mean()
    h, w = p.shape
    win = np.outer(np.hanning(h), np.hanning(w)).astype(np.float32)
    mag = np.abs(np.fft.fftshift(np.fft.fft2(p * win)))
    return mag.astype(np.float32)


def _tile_origins(h: int, w: int, tile: int) -> list[tuple[int, int]]:
    """Up to MAX_TILES origins spread over the image, always including the centre."""
    if h < tile or w < tile:
        return [(0, 0)]
    ys = sorted({0, (h - tile) // 2, h - tile})
    xs = sorted({0, (w - tile) // 2, w - tile})
    centre = ((h - tile) // 2, (w - tile) // 2)
    origins = [centre] + [(y, x) for y in ys for x in xs if (y, x) != centre]
    return origins[:MAX_TILES]


def _peak_mask(h: int, w: int) -> NDArray[np.bool_]:
    fy = np.fft.fftshift(np.fft.fftfreq(h))[:, None]
    fx = np.fft.fftshift(np.fft.fftfreq(w))[None, :]
    keep = np.ones((h, w), dtype=bool)
    keep &= np.sqrt(fx**2 + fy**2) > DC_RADIUS
    for k in range(1, 5):
        keep &= np.abs(np.abs(fx) - k / 8) > JPEG_TOLERANCE
        keep &= np.abs(np.abs(fy) - k / 8) > JPEG_TOLERANCE
    # Exact Nyquist rows/cols alias badly; drop them.
    keep &= np.abs(fx) < 0.49
    keep &= np.abs(fy) < 0.49
    return keep


def _local_ratio(mag: NDArray[np.float32]) -> NDArray[np.float32]:
    """Magnitude divided by the median of its NEIGHBOURHOOD x NEIGHBOURHOOD surroundings."""
    r = NEIGHBOURHOOD // 2
    padded = np.pad(mag, r, mode="reflect")
    windows = sliding_window_view(padded, (NEIGHBOURHOOD, NEIGHBOURHOOD))
    background = np.median(windows, axis=(-2, -1)).astype(np.float32)
    return mag / (background + 1e-6)


def _observation(res_measured: bool, detected: bool, peak_ratio: float, peaks: int) -> str:
    if not res_measured:
        return "The image is too small for a reliable resampling measurement."
    if detected:
        return (
            f"The prediction-residual spectrum contains {peaks} isolated peak(s) (strongest "
            f"{peak_ratio:.1f}x its surroundings), a periodic correlation consistent with the "
            "picture having been rescaled or rotated at some point. Routine resizing produces "
            "the same trace."
        )
    return (
        f"No isolated spectral peaks stand out (strongest {peak_ratio:.1f}x its surroundings). "
        "Either the picture was not rescaled, or compression, noise or content masks the trace."
    )


def analyze_resampling(data: bytes, *, min_peak_ratio: float = 5.0) -> ResamplingResult:
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        gray = np.asarray(img.convert("L"), dtype=np.float32)
    h, w = gray.shape
    if h < MIN_SIDE or w < MIN_SIDE:
        return ResamplingResult(
            False, w, h, 0, TILE, 0.0, [], False, _observation(False, False, 0, 0)
        )

    origins = _tile_origins(h, w, TILE)
    th, tw = min(TILE, h), min(TILE, w)
    acc: NDArray[np.float32] | None = None
    for y, x in origins:
        tile = gray[y : y + th, x : x + tw]
        spec = _spectrum(_pmap(_residual(tile)))
        acc = spec if acc is None else acc + spec
    assert acc is not None
    mag = (acc / len(origins)).astype(np.float32)

    ratio = _local_ratio(mag)
    keep = _peak_mask(*mag.shape)
    ratio_masked = np.where(keep, ratio, 0.0)
    fy = np.fft.fftshift(np.fft.fftfreq(mag.shape[0]))
    fx = np.fft.fftshift(np.fft.fftfreq(mag.shape[1]))

    peaks: list[SpectralPeak] = []
    flat = np.argsort(ratio_masked, axis=None)[::-1]
    for idx in flat[: MAX_PEAKS * 8]:
        iy, ix = np.unravel_index(idx, ratio_masked.shape)
        r = float(ratio_masked[iy, ix])
        if r < min_peak_ratio:
            break
        px, py = float(fx[ix]), float(fy[iy])
        # Keep one representative per symmetric pair and per neighbourhood.
        if any(abs(abs(q.fx) - abs(px)) < 0.01 and abs(abs(q.fy) - abs(py)) < 0.01 for q in peaks):
            continue
        peaks.append(SpectralPeak(fx=round(px, 4), fy=round(py, 4), ratio=round(r, 2)))
        if len(peaks) >= MAX_PEAKS:
            break
    peak_ratio = float(ratio_masked.max()) if ratio_masked.size else 0.0
    detected = len(peaks) > 0
    return ResamplingResult(
        measured=True,
        width=w,
        height=h,
        tiles=len(origins),
        tile_size=TILE,
        peak_ratio=round(peak_ratio, 2),
        peaks=peaks,
        detected=detected,
        observation=_observation(True, detected, peak_ratio, len(peaks)),
    )
