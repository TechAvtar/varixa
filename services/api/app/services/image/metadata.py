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
    color_profile: str | None = None
    image_width: int | None = None
    image_height: int | None = None
    tag_counts: dict[str, int] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        data = asdict(self)
        for key in ("captured_at", "modified_at"):
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
    n.color_profile = _text(raw.get("ICC_Profile", "ProfileDescription"))
    n.image_width = _int(raw.get("File", "ImageWidth") or raw.get("EXIF", "ExifImageWidth"))
    n.image_height = _int(raw.get("File", "ImageHeight") or raw.get("EXIF", "ExifImageHeight"))
    return n


def to_utc_or_none(ts: ParsedTimestamp | None) -> datetime | None:
    """DB column value: only timezone-known instants become UTC datetimes."""
    if ts is None or ts.parsed is None or not ts.tz_known:
        return None
    return ts.parsed.astimezone(UTC)
