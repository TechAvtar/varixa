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
    skipped: list[ForensicSkipped]
    artifacts: list[ForensicArtifactResponse]
    limitations: list[str]
