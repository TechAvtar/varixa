from typing import Literal

from pydantic import BaseModel

Confidence = Literal["low", "medium", "high"]


class ForensicRegionResponse(BaseModel):
    """Bounding box in original image pixels."""

    x: int
    y: int
    width: int
    height: int
    blocks: int
    mean_error: float


class ELAFindingResponse(BaseModel):
    method: Literal["ela"] = "ela"
    version: str
    observation: str
    confidence: Confidence
    anomaly: bool
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
    regions: list[ForensicRegionResponse]
    limitations: list[str]


class CompressionEncodingResponse(BaseModel):
    """Facts read from the JPEG headers (last save only)."""

    progressive: bool
    subsampling: str | None
    table_count: int
    estimated_quality: int | None
    standard_tables: bool
    luma_table_error: float | None
    chroma_estimated_quality: int | None
    has_jfif: bool
    has_adobe: bool


class BlockGridResponse(BaseModel):
    measured: bool
    aligned_strength: float
    offset_x: int
    offset_y: int
    offset_strength: float
    detected_aligned: bool
    detected_offset: bool
    profile_x: list[float]
    profile_y: list[float]


class CompressionFindingResponse(BaseModel):
    method: Literal["compression"] = "compression"
    version: str
    observation: str
    confidence: Confidence
    format: str
    lossless_container: bool
    encoding: CompressionEncodingResponse | None
    grid: BlockGridResponse
    # JPEG with a second, offset block grid (crop/shift then re-save).
    anomaly: bool
    # Non-JPEG file carrying a JPEG block grid (was probably a JPEG once).
    prior_jpeg_grid: bool
    limitations: list[str]


class SpectralPeakResponse(BaseModel):
    """Normalised frequency (cycles per pixel) and magnitude relative to the local background."""

    fx: float
    fy: float
    ratio: float


class ResamplingFindingResponse(BaseModel):
    method: Literal["resampling"] = "resampling"
    version: str
    observation: str
    confidence: Confidence
    measured: bool
    width: int
    height: int
    tiles: int
    tile_size: int
    peak_ratio: float
    peaks: list[SpectralPeakResponse]
    # Periodic correlations consistent with a global rescale/rotation. Not evidence of editing.
    detected: bool
    limitations: list[str]


class NoiseRegionResponse(BaseModel):
    """Bounding box in original image pixels; ``sigma`` is the region's mean noise estimate."""

    x: int
    y: int
    width: int
    height: int
    blocks: int
    sigma: float


class NoiseFindingResponse(BaseModel):
    method: Literal["noise"] = "noise"
    version: str
    observation: str
    confidence: Confidence
    measured: bool
    width: int
    height: int
    block_size: int
    blocks_total: int
    blocks_smooth: int
    baseline_sigma: float
    spread_sigma: float
    outlier_fraction: float
    regions: list[NoiseRegionResponse]
    # Compact regions whose noise level departs from the baseline. Never proof on its own.
    anomaly: bool
    limitations: list[str]


class ForensicSkipped(BaseModel):
    method: str
    reason: str


class ForensicArtifactResponse(BaseModel):
    name: str
    method: str
    content_type: str
    width: int
    height: int
    # Short-lived signed URL; never a raw storage key.
    url: str
    expires_in_seconds: int


class ImageForensicsResponse(BaseModel):
    ela: ELAFindingResponse | None
    compression: CompressionFindingResponse | None
    resampling: ResamplingFindingResponse | None
    noise: NoiseFindingResponse | None
    skipped: list[ForensicSkipped]
    artifacts: list[ForensicArtifactResponse]
    limitations: list[str]
