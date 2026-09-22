"""Content-credential (C2PA) inspection interface. Adapters report; they never judge."""

from dataclasses import dataclass, field
from typing import Any, Protocol


class ProvenanceInspectionError(Exception):
    """The engine ran but produced no usable result (timeout, crash, bad output)."""


@dataclass(frozen=True)
class RawProvenance:
    engine: str
    engine_version: str
    # False when the asset carries no manifest store at all ("No claim found").
    present: bool
    # c2patool summary JSON (active_manifest + manifests) when present.
    summary: dict[str, Any] | None = None
    # c2patool detailed JSON (-d) incl. validation_status when present.
    detailed: dict[str, Any] | None = None
    validation_status: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


class ProvenanceInspector(Protocol):
    name: str

    async def inspect(self, data: bytes, *, extension: str) -> RawProvenance: ...


class NullProvenanceInspector:
    """No engine available: reports UNKNOWN honestly instead of pretending to inspect."""

    name = "none"

    async def inspect(self, data: bytes, *, extension: str) -> RawProvenance:
        raise ProvenanceInspectionError("no C2PA engine is configured")
