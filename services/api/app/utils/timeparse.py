"""Best-effort parsing of the timestamp strings different subsystems record. Pure helpers."""

import re
from datetime import UTC, datetime, timedelta, timezone

_EXIF = re.compile(
    r"^(?P<y>\d{4})[:-](?P<m>\d{2})[:-](?P<d>\d{2})[ T](?P<H>\d{2}):(?P<M>\d{2}):(?P<S>\d{2})"
    r"(?:\.\d+)?(?P<tz>Z|[+-]\d{2}:?\d{2})?$"
)
_DATE = re.compile(r"^(?P<y>\d{4})-(?P<m>\d{2})-(?P<d>\d{2})$")


def parse_timestamp(value: object) -> tuple[datetime | None, bool]:
    """Return ``(datetime, tz_known)`` for RFC 3339, EXIF-style or plain-date strings.

    Naive values are returned naive (never silently assumed to be UTC); the caller
    decides what a missing timezone means for its comparison. Unparseable input
    yields ``(None, False)``.
    """
    if value is None:
        return None, False
    if isinstance(value, datetime):
        return value, value.tzinfo is not None
    raw = str(value).strip()
    if not raw or raw.startswith("0000"):
        return None, False
    m = _EXIF.match(raw)
    if m:
        try:
            dt = datetime(
                int(m["y"]), int(m["m"]), int(m["d"]), int(m["H"]), int(m["M"]), int(m["S"])
            )
        except ValueError:
            return None, False
        tz = m["tz"]
        if not tz:
            return dt, False
        if tz == "Z":
            return dt.replace(tzinfo=UTC), True
        sign = 1 if tz[0] == "+" else -1
        digits = tz[1:].replace(":", "")
        offset = sign * (int(digits[:2]) * 60 + int(digits[2:]))
        return dt.replace(tzinfo=timezone(timedelta(minutes=offset))), True
    m = _DATE.match(raw)
    if m:
        try:
            return datetime(int(m["y"]), int(m["m"]), int(m["d"])), False
        except ValueError:
            return None, False
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None, False
    return dt, dt.tzinfo is not None


def as_utc(dt: datetime) -> datetime:
    """Comparable UTC value: aware values are converted, naive ones are *assumed* UTC."""
    return dt.astimezone(UTC) if dt.tzinfo is not None else dt.replace(tzinfo=UTC)
