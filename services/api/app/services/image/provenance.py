"""Normalises c2patool output into an engine-independent provenance summary.

Epistemics matter here:
- No manifest => UNKNOWN. It is never evidence of manipulation or AI generation.
- A validated signature proves the manifest is intact and was signed by the
  holder of the certificate named as issuer. It does not prove the claims are
  true. Whether that certificate chains to a trust list is a *separate*
  observation (a trust failure never reads as "manifest altered").
"""

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from app.providers.provenance.base import RawProvenance
from app.services.image.provenance_depth import read_depth

CodeFamily = Literal["integrity", "trust", "identity", "info"]

_SIGNATURE_OK = "claimSignature.validated"

# Validation code families (c2pa-rs ValidationStatus codes). Trust and identity codes are
# never treated as integrity failures; unknown codes fall back to a conservative regex.
_TRUST_CODES = {
    "signingCredential.untrusted",
    "signingCredential.trusted",
    "signingCredential.expired",
    "signingCredential.revoked",
    "signingCredential.invalid",
    "signingCredential.ocsp.unknown",
    "signingCredential.ocsp.revoked",
    "signingCredential.ocsp.inaccessible",
    "timeStamp.untrusted",
    "timeStamp.trusted",
    "timeStamp.mismatch",
    "timeStamp.outsideValidity",
}
_SUCCESS_CODES = {
    _SIGNATURE_OK,
    "assertion.hashedURI.match",
    "assertion.dataHash.match",
    "assertion.bmffHash.match",
    "assertion.boxesHash.match",
    "assertion.collectionHash.match",
    "ingredient.manifest.validated",
    "ingredient.claimSignature.validated",
    "timeStamp.validated",
    "claim.signature.validated",
}
_FAILURE_RE = re.compile(
    r"(mismatch|invalid|expired|revoked|error|missing|failure|malformed|notFound|unsupported)",
    re.I,
)

MAX_ACTIONS = 100
MAX_ASSERTIONS = 200
MAX_CODES = 200


def classify_code(code: str, explanation: str | None = None) -> CodeFamily:
    """Which question a validation code answers.

    ``integrity``: the manifest bytes and hashes (a failure means altered or mismatched).
    ``trust``: whether the signing certificate chains to a configured trust list.
    ``identity``: CAWG identity assertions (validated by the engine's own identity trust).
    ``info``: successes and neutral notes.
    """
    if (
        code in _TRUST_CODES
        or code.startswith("signingCredential.")
        or code.startswith("timeStamp.")
    ):
        return "trust"
    if code.startswith("cawg."):
        return "identity"
    if code in _SUCCESS_CODES:
        return "info"
    if code == "general.error":
        # c2patool 0.9.x mirrors an untrusted certificate as a general error too.
        text = (explanation or "").lower()
        if "untrusted" in text or "trust" in text:
            return "trust"
        return "integrity"
    if _FAILURE_RE.search(code):
        return "integrity"
    return "info"


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
    # Structured view of the validation outcome: engine state (when the engine reports one),
    # per-family code lists for the active manifest, and per-ingredient results.
    validation: dict[str, Any] = field(default_factory=dict)
    # `--info` facts: manifest store size and count as reported by the engine.
    info: dict[str, Any] = field(default_factory=dict)
    # Signed declarations read from the active manifest (T045): hash coverage, training/mining
    # permissions, action source types, identity presence.
    assertions: dict[str, Any] = field(default_factory=dict)
    software_agents: list[dict[str, Any]] = field(default_factory=list)
    # Ingredient tree (recursive nodes with per-ingredient validation codes).
    ingredients: list[dict[str, Any]] = field(default_factory=list)
    ingredient_failures: int = 0
    # Every manifest in the store, active first, with signing times; a child signed after its
    # parent is an ordering conflict.
    manifest_chain: list[dict[str, Any]] = field(default_factory=list)
    manifest_order_conflict: bool = False

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _str(value: Any, limit: int = 300) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def _empty_families() -> dict[str, list[str]]:
    return {"success": [], "informational": [], "failure": []}


def _codes_from_results_block(block: Any) -> dict[str, list[str]]:
    """c2pa-rs `validation_results` block: {success: [...], informational: [...], failure: [...]}
    where each entry is a status object. Codes only; explanations stay in raw."""
    out = _empty_families()
    if not isinstance(block, dict):
        return out
    for family in ("success", "informational", "failure"):
        for entry in (block.get(family) or [])[:MAX_CODES]:
            code = _str(entry.get("code"), 120) if isinstance(entry, dict) else None
            if code:
                out[family].append(code)
    return out


def _structured_validation(raw: RawProvenance) -> dict[str, Any]:
    """Prefer the engine's structured results; otherwise synthesise them from the flat list
    with `classify_code` so both engine generations produce the same shape."""
    validation: dict[str, Any] = {
        "state": raw.validation_state,
        "source": "validation_results" if raw.validation_results else "validation_status",
        "active_manifest": _empty_families(),
        "ingredients": {},
    }
    if raw.validation_results:
        active = raw.validation_results.get("activeManifest") or raw.validation_results.get(
            "active_manifest"
        )
        validation["active_manifest"] = _codes_from_results_block(active)
        ingredients = raw.validation_results.get("ingredientDeltas") or raw.validation_results.get(
            "ingredient_deltas"
        )
        if isinstance(ingredients, list):
            for delta in ingredients[:MAX_CODES]:
                if not isinstance(delta, dict):
                    continue
                label = _str(delta.get("ingredientAssertionURI") or delta.get("label"), 200)
                if label:
                    validation["ingredients"][label] = _codes_from_results_block(
                        delta.get("validationDeltas") or delta.get("validation_deltas")
                    )
        return validation
    families = validation["active_manifest"]
    for status in raw.validation_status[:MAX_CODES]:
        code = _str(status.get("code"), 120)
        if not code:
            continue
        family = classify_code(code, _str(status.get("explanation"), 500))
        if family == "info":
            families["success" if code in _SUCCESS_CODES else "informational"].append(code)
        elif family == "integrity":
            families["failure"].append(code)
        else:
            families["informational"].append(code)
    return validation


_INFO_SIZE_RE = re.compile(r"Manifest store size = (\d+)")
_INFO_COUNT_RE = re.compile(r"(One|\d+) manifests?", re.I)


def _parse_info(text: str | None) -> dict[str, Any]:
    if not text:
        return {}
    out: dict[str, Any] = {}
    m = _INFO_SIZE_RE.search(text)
    if m:
        out["manifest_store_bytes"] = int(m.group(1))
    m = _INFO_COUNT_RE.search(text)
    if m:
        word = m.group(1)
        out["manifest_count"] = 1 if word.lower() == "one" else int(word)
    if "Validated" in text:
        out["validated"] = True
    elif "error" in text.lower():
        out["validated"] = False
    return out


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

    for status in raw.validation_status[:MAX_CODES]:
        code = _str(status.get("code"), 120)
        if not code:
            continue
        n.validation_codes.append(code)
        explanation = _str(status.get("explanation"), 500)
        if classify_code(code, explanation) == "integrity":
            n.validation_failures.append({"code": code, "explanation": explanation})

    n.validation = _structured_validation(raw)
    n.info = _parse_info(raw.info)
    depth = read_depth(raw.summary, raw.detailed, n.active_manifest, classify_code)
    n.assertions = depth.assertions
    n.software_agents = depth.software_agents
    n.ingredients = depth.ingredients
    n.ingredient_failures = depth.ingredient_failures
    n.manifest_chain = depth.manifest_chain
    n.manifest_order_conflict = depth.manifest_order_conflict
    if raw.validation_results:
        # Structured results are authoritative when present: any integrity failure there
        # counts, even if the flat list is empty.
        failures = n.validation["active_manifest"]["failure"]
        known = {f["code"] for f in n.validation_failures}
        for code in failures:
            if code not in known and classify_code(code) == "integrity":
                n.validation_failures.append({"code": code, "explanation": None})
        successes = n.validation["active_manifest"]["success"]
        signed_ok = _SIGNATURE_OK in n.validation_codes or _SIGNATURE_OK in successes
    else:
        signed_ok = _SIGNATURE_OK in n.validation_codes
    n.valid_signature = signed_ok and not n.validation_failures
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
            "Only the active manifest is summarised in full; earlier manifests appear in the "
            "manifest chain and the raw data."
        )
    if n.assertions.get("source_types") or n.assertions.get("training_mining"):
        notes.append(
            "Declared source types and training/mining permissions are the signer's statements: "
            "verified as stated, not as true."
        )
    if n.ingredient_failures:
        notes.append(
            "Some ingredients carry validation failures recorded at composition time; the active "
            "manifest can still validate on its own."
        )
    return notes
