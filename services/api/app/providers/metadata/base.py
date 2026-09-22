"""Metadata extraction interface. Adapters return raw, grouped tags; they never interpret."""

from dataclasses import dataclass, field
from typing import Any, Protocol

# Raw tag value after size capping: scalars, lists, or nested dicts (ExifTool -struct).
RawValue = Any
RawGroups = dict[str, dict[str, RawValue]]

MAX_STRING_VALUE = 4096
MAX_TAGS = 5000


class MetadataExtractionError(Exception):
    """The engine ran but could not produce output (timeout, crash, bad JSON)."""


@dataclass(frozen=True)
class RawMetadata:
    engine: str
    engine_version: str
    # e.g. {"EXIF": {"IFD0:Make": "Canon"}, "XMP": {...}, "ICC_Profile": {...}, "File": {...}}
    groups: RawGroups = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    def group(self, name: str) -> dict[str, RawValue]:
        return self.groups.get(name, {})

    def get(self, group: str, tag: str) -> RawValue | None:
        """Look up a tag within a group by its unqualified name (e.g. ``Make``)."""
        for key, value in self.group(group).items():
            if key == tag or key.endswith(":" + tag):
                return value
        return None


class MetadataExtractor(Protocol):
    name: str

    async def extract(self, data: bytes) -> RawMetadata: ...


def cap_value(value: RawValue) -> RawValue:
    """Bound stored sizes so a hostile file cannot bloat the database."""
    if isinstance(value, str) and len(value) > MAX_STRING_VALUE:
        return value[:MAX_STRING_VALUE] + f"... [truncated {len(value) - MAX_STRING_VALUE} chars]"
    if isinstance(value, bytes):
        return f"(Binary data {len(value)} bytes)"
    if isinstance(value, list):
        return [cap_value(v) for v in value[:256]]
    if isinstance(value, dict):
        return {str(k): cap_value(v) for k, v in list(value.items())[:256]}
    return value
