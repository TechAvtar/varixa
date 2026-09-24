from typing import Any

from pydantic import BaseModel


class ProvenanceActionResponse(BaseModel):
    action: str | None
    when: str | None
    software_agent: str | None
    parameters: Any | None = None


class ProvenanceValidationFailure(BaseModel):
    code: str
    explanation: str | None


class NormalizedProvenanceResponse(BaseModel):
    engine: str
    engine_version: str
    has_c2pa: bool
    valid_signature: bool | None
    signer: str | None
    signature_alg: str | None
    signed_at: str | None
    claim_generator: str | None
    title: str | None
    active_manifest: str | None
    manifest_count: int
    ingredient_count: int
    assertion_labels: list[str]
    actions: list[ProvenanceActionResponse]
    authors: list[str]
    validation_codes: list[str]
    validation_failures: list[ProvenanceValidationFailure]
    warnings: list[str]
    # Structured validation view (state, per-family codes for the active manifest and
    # per-ingredient results) and `--info` facts; empty for rows written before T044.
    validation: dict[str, Any] = {}
    info: dict[str, Any] = {}
    # T045: signed declarations, software agents, ingredient tree and manifest chain.
    assertions: dict[str, Any] = {}
    software_agents: list[dict[str, Any]] = []
    ingredients: list[dict[str, Any]] = []
    ingredient_failures: int = 0
    manifest_chain: list[dict[str, Any]] = []
    manifest_order_conflict: bool = False


class ImageProvenanceResponse(BaseModel):
    normalized: NormalizedProvenanceResponse
    manifests: dict[str, Any]
    validation_status: list[dict[str, Any]]
    limitations: list[str]
    # `c2patool --tree` text diagram of the manifest store, when the engine produced one.
    tree: str | None = None
