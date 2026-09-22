import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict


class FingerprintsResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sha256: str
    md5: str
    phash: str
    dhash: str
    ahash: str
    algorithm_version: str


class SimilarAnalysisResponse(BaseModel):
    analysis_id: uuid.UUID
    title: str | None
    created_at: datetime
    relation: Literal["exact", "near"]
    sha256_match: bool
    phash_distance: int
    dhash_distance: int
    ahash_distance: int


class ImageFingerprintsResponse(BaseModel):
    kind: Literal["image"] = "image"
    fingerprints: FingerprintsResponse
    near_threshold: int
    similar: list[SimilarAnalysisResponse]
    limitations: list[str]


class TextFingerprintsValues(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    sha256: str
    normalized_sha256: str
    canonical_sha256: str
    shingle_count: int
    algorithm_version: str


class SimilarTextResponse(BaseModel):
    analysis_id: uuid.UUID
    title: str | None
    created_at: datetime
    relation: Literal["exact", "normalized", "canonical", "near"]
    estimated_jaccard: float


class TextFingerprintsResponse(BaseModel):
    kind: Literal["text"] = "text"
    fingerprints: TextFingerprintsValues
    near_threshold: float
    similar: list[SimilarTextResponse]
    limitations: list[str]
