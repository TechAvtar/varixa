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
    # Newer engines (c2pa-rs >= 0.4x) report a structured result per manifest and an
    # overall state ("Invalid" | "Valid" | "Trusted"); older ones only the flat status list.
    validation_results: dict[str, Any] | None = None
    validation_state: str | None = None
    # Human-readable `--info` report (size of the manifest store, count, validated/errors).
    info: str | None = None
    # What the engine binary supports (version, flag names); informational only.
    capabilities: dict[str, Any] = field(default_factory=dict)
    # `--tree` text diagram of the manifest store (raw only; never interpreted).
    tree: str | None = None
    # The asset points at a manifest hosted elsewhere and the engine did not fetch it
    # (fetching is disabled). Host only; the path never leaves the adapter.
    remote_manifest_host: str | None = None
    # Trust run (separate from integrity): whether the signing certificate chains to the
    # configured trust list. `trust_state` is the engine's overall state when it reports
    # one (Invalid | Valid | Trusted); the status list / results carry the trust codes.
    trust_evaluated: bool = False
    trust_mode: str | None = None
    trust_list_version: str | None = None
    trust_state: str | None = None
    trust_status: list[dict[str, Any]] = field(default_factory=list)
    trust_results: dict[str, Any] | None = None
    # `--certs`: PEM chain of the active manifest's signature, leaf first (public certs).
    certificates_pem: str | None = None
    # The thumbnail assertion signed into the active manifest (`c2pa.thumbnail.claim.*`),
    # extracted to memory for the comparison step; never stored in the raw row.
    claim_thumbnail: bytes | None = field(default=None, repr=False)
    claim_thumbnail_format: str | None = None
    # True when the manifest came from a sidecar supplied with the upload.
    sidecar_used: bool = False


class ProvenanceInspector(Protocol):
    name: str

    async def inspect(
        self, data: bytes, *, extension: str, sidecar: bytes | None = None
    ) -> RawProvenance: ...


class NullProvenanceInspector:
    """No engine available: reports UNKNOWN honestly instead of pretending to inspect."""

    name = "none"

    async def inspect(
        self, data: bytes, *, extension: str, sidecar: bytes | None = None
    ) -> RawProvenance:
        raise ProvenanceInspectionError("no C2PA engine is configured")
