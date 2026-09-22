from typing import Any

from pydantic import BaseModel


class ParsedTimestampResponse(BaseModel):
    raw: str
    parsed: str | None
    tz_known: bool


class NormalizedMetadataResponse(BaseModel):
    engine: str
    engine_version: str
    has_exif: bool
    has_xmp: bool
    has_iptc: bool
    has_icc: bool
    has_makernotes: bool
    camera_make: str | None
    camera_model: str | None
    lens: str | None
    software: str | None
    captured_at: ParsedTimestampResponse | None
    modified_at: ParsedTimestampResponse | None
    orientation: int | None
    orientation_label: str | None
    gps_present: bool
    color_profile: str | None
    image_width: int | None
    image_height: int | None
    tag_counts: dict[str, int]
    warnings: list[str]


class ImageMetadataResponse(BaseModel):
    normalized: NormalizedMetadataResponse
    exif: dict[str, Any]
    xmp: dict[str, Any]
    iptc: dict[str, Any]
    icc: dict[str, Any]
    other: dict[str, dict[str, Any]]
    limitations: list[str]
