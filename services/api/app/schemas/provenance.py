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


class ImageProvenanceResponse(BaseModel):
    normalized: NormalizedProvenanceResponse
    manifests: dict[str, Any]
    validation_status: list[dict[str, Any]]
    limitations: list[str]
