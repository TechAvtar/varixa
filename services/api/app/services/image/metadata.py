"""Normalises raw metadata into a small, engine-independent shape.

Every normalised field is a *recorded value*, not a verified fact: EXIF can be
edited freely. Absence of metadata says nothing about editing. Timestamps keep
their original text and gain a parsed form only when unambiguous.
"""

import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

from app.providers.metadata.base import RawMetadata
from app.services.image.lineage import extract_lineage

_EXIF_DT = re.compile(
    r"^(?P<y>\d{4})[:\-](?P<m>\d{2})[:\-](?P<d>\d{2})[ T](?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2})"
    r"(?:\.(?P<f>\d{1,6}))?(?P<tz>Z|[+\-]\d{2}:?\d{2})?"
)

ORIENTATIONS = {
    1: "Horizontal (normal)",
    2: "Mirror horizontal",
    3: "Rotate 180",
    4: "Mirror vertical",
    5: "Mirror horizontal and rotate 270 CW",
    6: "Rotate 90 CW",
    7: "Mirror horizontal and rotate 90 CW",
    8: "Rotate 270 CW",
}


@dataclass(frozen=True)
class ParsedTimestamp:
    raw: str
    parsed: datetime | None  # tz-aware when an offset was present, else naive
    tz_known: bool


@dataclass
class NormalizedMetadata:
    engine: str
    engine_version: str
    has_exif: bool = False
    has_xmp: bool = False
    has_iptc: bool = False
    has_icc: bool = False
    has_makernotes: bool = False
    camera_make: str | None = None
    camera_model: str | None = None
    lens: str | None = None
    software: str | None = None
    captured_at: ParsedTimestamp | None = None
    modified_at: ParsedTimestamp | None = None
    orientation: int | None = None
    orientation_label: str | None = None
    gps_present: bool = False
    # Decimal degrees (WGS84 as recorded; south/west negative), metres, and the GPS receiver's
    # own UTC time. All recorded values: trivially editable, never verified.
    gps_latitude: float | None = None
    gps_longitude: float | None = None
    gps_altitude_m: float | None = None
    gps_time: ParsedTimestamp | None = None
    color_profile: str | None = None
    # Declared lineage (docs/05): generator markers, IPTC digital source type, XMP edit history.
    generator: str | None = None
    generator_signals: list[dict[str, Any]] = field(default_factory=list)
    digital_source_type: str | None = None
    creator_tool: str | None = None
    document_id: str | None = None
    instance_id: str | None = None
    original_document_id: str | None = None
    derived_from_document_id: str | None = None
    edit_history: list[dict[str, Any]] = field(default_factory=list)
    provenance_url: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    tag_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("captured_at", "modified_at", "gps_time"):
            ts = getattr(self, key)
            data[key] = (
                None
                if ts is None
                else {
                    "raw": ts.raw,
                    "parsed": ts.parsed.isoformat() if ts.parsed else None,
                    "tz_known": ts.tz_known,
                }
            )
        return data


def parse_exif_datetime(value: Any, offset: Any = None) -> ParsedTimestamp | None:
    """Parse ``YYYY:MM:DD HH:MM:SS[.fff][±HH:MM]``; ``offset`` is a separate OffsetTime tag."""
    if value is None:
        return None
    raw = str(value).strip()
    m = _EXIF_DT.match(raw)
    if not m or raw.startswith("0000"):
        return ParsedTimestamp(raw=raw, parsed=None, tz_known=False)
    try:
        dt = datetime(
            int(m["y"]),
            int(m["m"]),
            int(m["d"]),
            int(m["H"]),
            int(m["M"]),
            int(m["S"]),
            int((m["f"] or "0").ljust(6, "0")),
        )
    except ValueError:
        return ParsedTimestamp(raw=raw, parsed=None, tz_known=False)
    tz_text = m["tz"] or (str(offset).strip() if offset else None)
    if tz_text:
        if tz_text == "Z":
            return ParsedTimestamp(raw=raw, parsed=dt.replace(tzinfo=UTC), tz_known=True)
        tzm = re.match(r"^([+\-])(\d{2}):?(\d{2})$", tz_text)
        if tzm:
            sign = 1 if tzm[1] == "+" else -1
            delta = timedelta(hours=int(tzm[2]), minutes=int(tzm[3])) * sign
            return ParsedTimestamp(
                raw=raw, parsed=dt.replace(tzinfo=timezone(delta)), tz_known=True
            )
    return ParsedTimestamp(raw=raw, parsed=dt, tz_known=False)


def _degrees(value: Any) -> float | None:
    """Decimal degrees from a number, a numeric string, or a [deg, min, sec] list."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    if isinstance(value, list | tuple) and 1 <= len(value) <= 3:
        parts = [_degrees(v) for v in value]
        if any(p is None for p in parts):
            return None
        padded = [float(p) for p in parts if p is not None] + [0.0, 0.0]
        deg, minute, sec = padded[0], padded[1], padded[2]
        return deg + minute / 60 + sec / 3600
    return None


def _signed(value: float | None, ref: Any, negative_refs: tuple[str, ...]) -> float | None:
    if value is None:
        return None
    ref_text = str(ref).strip().upper() if ref is not None else ""
    if ref_text[:1] in negative_refs and value > 0:
        return -value
    return value


def gps_coordinates(raw: RawMetadata) -> tuple[float | None, float | None, list[str]]:
    """(latitude, longitude) in decimal degrees, or None each, plus warnings for bad values.

    Prefers ExifTool's signed ``Composite`` values; otherwise combines the EXIF GPS tags
    (decimal with ``-n``, or degree/minute/second lists from Pillow) with their N/S, E/W refs.
    """
    warnings: list[str] = []
    lat = _degrees(raw.get("Composite", "GPSLatitude"))
    lon = _degrees(raw.get("Composite", "GPSLongitude"))
    if lat is None:
        lat = _signed(
            _degrees(raw.get("EXIF", "GPSLatitude")), raw.get("EXIF", "GPSLatitudeRef"), ("S",)
        )
    if lon is None:
        lon = _signed(
            _degrees(raw.get("EXIF", "GPSLongitude")), raw.get("EXIF", "GPSLongitudeRef"), ("W",)
        )
    if lat is not None and not -90 <= lat <= 90:
        warnings.append(f"GPS latitude out of range: {lat}")
        lat = None
    if lon is not None and not -180 <= lon <= 180:
        warnings.append(f"GPS longitude out of range: {lon}")
        lon = None
    if (lat is None) != (lon is None):
        warnings.append("GPS position incomplete: only one coordinate recorded")
        lat = lon = None
    return lat, lon, warnings


def gps_altitude(raw: RawMetadata) -> float | None:
    alt = _degrees(raw.get("EXIF", "GPSAltitude"))
    if alt is None:
        return None
    ref = raw.get("EXIF", "GPSAltitudeRef")
    below = str(ref).strip().lower() in {"1", "b'\\x01'", "below sea level"} or ref in (1, b"\x01")
    return -abs(alt) if below else alt


def gps_time(raw: RawMetadata) -> ParsedTimestamp | None:
    """The receiver's UTC time from Composite:GPSDateTime or GPSDateStamp + GPSTimeStamp."""
    composite = raw.get("Composite", "GPSDateTime")
    if composite:
        return parse_exif_datetime(composite, "Z")
    date = raw.get("EXIF", "GPSDateStamp")
    time_value = raw.get("EXIF", "GPSTimeStamp")
    if not date or time_value is None:
        return None
    if isinstance(time_value, list | tuple) and len(time_value) == 3:
        try:
            h, m, s = (int(float(x)) for x in time_value)
        except (TypeError, ValueError):
            return None
        clock = f"{h:02d}:{m:02d}:{s:02d}"
    else:
        clock = str(time_value).strip()[:8]
    return parse_exif_datetime(f"{str(date).strip()} {clock}", "Z")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().strip("\x00")
    return text[:200] or None


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def normalize_metadata(raw: RawMetadata) -> NormalizedMetadata:
    n = NormalizedMetadata(engine=raw.engine, engine_version=raw.engine_version)
    n.tag_counts = {g: len(tags) for g, tags in raw.groups.items() if tags}
    n.warnings = list(raw.warnings)
    n.has_exif = bool(raw.group("EXIF"))
    n.has_xmp = bool(raw.group("XMP"))
    n.has_iptc = bool(raw.group("IPTC"))
    n.has_icc = bool(raw.group("ICC_Profile"))
    n.has_makernotes = bool(raw.group("MakerNotes"))

    n.camera_make = _text(raw.get("EXIF", "Make") or raw.get("XMP", "Make"))
    n.camera_model = _text(raw.get("EXIF", "Model") or raw.get("XMP", "Model"))
    n.lens = _text(
        raw.get("EXIF", "LensModel") or raw.get("XMP", "Lens") or raw.get("Composite", "LensID")
    )
    n.software = _text(
        raw.get("EXIF", "Software") or raw.get("XMP", "CreatorTool") or raw.get("XMP", "Software")
    )
    n.captured_at = parse_exif_datetime(
        raw.get("EXIF", "DateTimeOriginal")
        or raw.get("XMP", "DateTimeOriginal")
        or raw.get("EXIF", "CreateDate"),
        raw.get("EXIF", "OffsetTimeOriginal") or raw.get("EXIF", "OffsetTime"),
    )
    n.modified_at = parse_exif_datetime(
        raw.get("EXIF", "ModifyDate") or raw.get("XMP", "ModifyDate"),
        raw.get("EXIF", "OffsetTime"),
    )
    n.orientation = _int(raw.get("EXIF", "Orientation"))
    n.orientation_label = ORIENTATIONS.get(n.orientation) if n.orientation else None

    gps = raw.group("EXIF")
    n.gps_present = any(
        k.split(":")[-1].startswith("GPS") and v not in (None, "", [], {}) for k, v in gps.items()
    ) or (raw.get("Composite", "GPSPosition") is not None)
    if n.gps_present:
        n.gps_latitude, n.gps_longitude, gps_warnings = gps_coordinates(raw)
        n.warnings.extend(gps_warnings)
        n.gps_altitude_m = gps_altitude(raw)
        n.gps_time = gps_time(raw)
    n.color_profile = _text(raw.get("ICC_Profile", "ProfileDescription"))
    lineage = extract_lineage(raw).to_json()
    for key in (
        "generator",
        "generator_signals",
        "digital_source_type",
        "creator_tool",
        "document_id",
        "instance_id",
        "original_document_id",
        "derived_from_document_id",
        "edit_history",
        "provenance_url",
    ):
        setattr(n, key, lineage[key])
    if n.software is None and n.creator_tool:
        n.software = n.creator_tool
    n.image_width = _int(raw.get("File", "ImageWidth") or raw.get("EXIF", "ExifImageWidth"))
    n.image_height = _int(raw.get("File", "ImageHeight") or raw.get("EXIF", "ExifImageHeight"))
    return n


def to_utc_or_none(ts: ParsedTimestamp | None) -> datetime | None:
    """DB column value: only timezone-known instants become UTC datetimes."""
    if ts is None or ts.parsed is None or not ts.tz_known:
        return None
    return ts.parsed.astimezone(UTC)
