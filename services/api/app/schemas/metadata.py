from typing import Any

from pydantic import BaseModel, Field


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
    # Recorded GPS values (decimal degrees, metres, receiver UTC time); editable, never verified.
    gps_latitude: float | None = None
    gps_longitude: float | None = None
    gps_altitude_m: float | None = None
    gps_time: ParsedTimestampResponse | None = None
    color_profile: str | None
    # Declared lineage: generator markers, IPTC digital source type, XMP document ids/history.
    generator: str | None = None
    generator_signals: list[dict[str, Any]] = Field(default_factory=list)
    digital_source_type: str | None = None
    creator_tool: str | None = None
    document_id: str | None = None
    instance_id: str | None = None
    original_document_id: str | None = None
    derived_from_document_id: str | None = None
    edit_history: list[dict[str, Any]] = Field(default_factory=list)
    # Remote Content Credentials reference (XMP dcterms:provenance); recorded, never fetched.
    provenance_url: str | None = None
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
