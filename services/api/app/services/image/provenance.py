"""Normalises c2patool output into an engine-independent provenance summary.

Epistemics matter here:
- No manifest => UNKNOWN. It is never evidence of manipulation or AI generation.
- A validated signature proves the manifest is intact and was signed by the
  holder of the certificate named as issuer. It does not prove the claims are
  true, nor that the issuer is trustworthy (trust lists are not evaluated).
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from app.providers.provenance.base import RawProvenance

# Any status code matching these is treated as a validation failure.
_FAILURE_RE = re.compile(
    r"(mismatch|invalid|untrusted|expired|revoked|error|missing|failure)", re.I
)
_SIGNATURE_OK = "claimSignature.validated"

MAX_ACTIONS = 100
MAX_ASSERTIONS = 200


@dataclass
class NormalizedProvenance:
    engine: str
    engine_version: str
    has_c2pa: bool
    # None when no manifest exists (nothing to validate).
    valid_signature: bool | None = None
    signer: str | None = None
    signature_alg: str | None = None
    signed_at: str | None = None  # as reported by the tool (RFC 3339)
    claim_generator: str | None = None
    title: str | None = None
    active_manifest: str | None = None
    manifest_count: int = 0
    ingredient_count: int = 0
    assertion_labels: list[str] = field(default_factory=list)
    actions: list[dict[str, Any]] = field(default_factory=list)
    authors: list[str] = field(default_factory=list)
    validation_codes: list[str] = field(default_factory=list)
    validation_failures: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _str(value: Any, limit: int = 300) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def normalize_provenance(raw: RawProvenance) -> NormalizedProvenance:
    n = NormalizedProvenance(
        engine=raw.engine, engine_version=raw.engine_version, has_c2pa=raw.present
    )
    n.warnings = list(raw.warnings)
    if not raw.present or not raw.summary:
        return n

    manifests = raw.summary.get("manifests") or {}
    n.manifest_count = len(manifests) if isinstance(manifests, dict) else 0
    n.active_manifest = _str(raw.summary.get("active_manifest"))
    active = manifests.get(n.active_manifest) if isinstance(manifests, dict) else None
    if not isinstance(active, dict):
        active = (
            next((m for m in manifests.values() if isinstance(m, dict)), {}) if manifests else {}
        )

    n.claim_generator = _str(active.get("claim_generator"))
    n.title = _str(active.get("title"))
    ingredients = active.get("ingredients") or []
    n.ingredient_count = len(ingredients) if isinstance(ingredients, list) else 0

    sig = active.get("signature_info") or {}
    if isinstance(sig, dict):
        n.signer = _str(sig.get("issuer"))
        n.signature_alg = _str(sig.get("alg"))
        n.signed_at = _str(sig.get("time"))

    for assertion in (active.get("assertions") or [])[:MAX_ASSERTIONS]:
        if not isinstance(assertion, dict):
            continue
        label = _str(assertion.get("label"))
        if label:
            n.assertion_labels.append(label)
        data = assertion.get("data")
        if label == "c2pa.actions" and isinstance(data, dict):
            for action in (data.get("actions") or [])[:MAX_ACTIONS]:
                if isinstance(action, dict):
                    n.actions.append(
                        {
                            "action": _str(action.get("action")),
                            "when": _str(action.get("when")),
                            "software_agent": _str(action.get("softwareAgent")),
                            "parameters": action.get("parameters"),
                        }
                    )
        if label == "stds.schema-org.CreativeWork" and isinstance(data, dict):
            for author in data.get("author") or []:
                name = author.get("name") if isinstance(author, dict) else None
                if _str(name):
                    n.authors.append(str(name)[:200])

    for status in raw.validation_status:
        code = _str(status.get("code"), 120)
        if not code:
            continue
        n.validation_codes.append(code)
        if _FAILURE_RE.search(code):
            n.validation_failures.append(
                {"code": code, "explanation": _str(status.get("explanation"), 500)}
            )

    n.valid_signature = _SIGNATURE_OK in n.validation_codes and not n.validation_failures
    return n


def provenance_limitations(n: NormalizedProvenance) -> list[str]:
    notes: list[str] = []
    if not n.has_c2pa:
        notes.append(
            "No content credentials (C2PA) were found. This does not establish whether the "
            "file was edited, generated, or authentic; most images carry no credentials."
        )
        return notes
    notes.append(
        "A valid signature shows the manifest is intact and was signed with the named "
        "certificate. It does not prove the claims are true."
    )
    notes.append(
        "Issuer trust (certificate chain against a trust list) is not evaluated in this build; "
        "'signer' is the certificate's stated issuer, not a verified identity."
    )
    if n.valid_signature is False:
        notes.append(
            "Validation reported problems; the manifest may have been altered, or the file "
            "changed after signing. Treat all claims with caution."
        )
    if n.manifest_count > 1:
        notes.append(
            "Only the active manifest is summarised; earlier manifests are in the raw data."
        )
    return notes
