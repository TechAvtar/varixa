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
    signer_common_name: str | None = None  # certificate subject CN (0.28+ engines report it)
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
    # Where the manifest came from: embedded | remote | sidecar | none | unknown.
    manifest_location: str = "unknown"
    # Host of a remote manifest the engine did not fetch (fetching is disabled).
    remote_manifest_host: str | None = None
    # Trust run (T047): None = not evaluated; True/False = the signing certificate does /
    # does not chain to the configured trust list. Details in `trust`.
    trusted: bool | None = None
    trust: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def _str(value: Any, limit: int = 300) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def _agent_name(value: Any) -> str | None:
    """`softwareAgent` is a string in v1 actions and {name, version} in v2."""
    if isinstance(value, dict):
        name, version = _str(value.get("name"), 200), _str(value.get("version"), 80)
        return f"{name} {version}".strip() if name else None
    return _str(value)


def _empty_families() -> dict[str, list[str]]:
    return {"success": [], "informational": [], "failure": []}


def _empty_families_full() -> dict[str, list[str]]:
    return {"success": [], "informational": [], "failure": [], "trust": [], "identity": []}


def _codes_from_results_block(block: Any) -> dict[str, list[str]]:
    """c2pa-rs `validation_results` block: {success: [...], informational: [...], failure: [...]}
    where each entry is a status object. Codes only; explanations stay in raw.

    The engine files an unlisted signer under *failure*; Verixa keeps `failure` for
    integrity problems and moves trust and identity codes into their own families."""
    out = _empty_families_full()
    if not isinstance(block, dict):
        return out
    for family in ("success", "informational", "failure"):
        for entry in (block.get(family) or [])[:MAX_CODES]:
            code = _str(entry.get("code"), 120) if isinstance(entry, dict) else None
            if not code:
                continue
            kind = classify_code(code, _str(entry.get("explanation"), 500))
            if kind == "trust":
                out["trust"].append(code)
            elif kind == "identity":
                out["identity"].append(code)
            elif family == "failure" and kind != "integrity":
                out["informational"].append(code)
            else:
                out[family].append(code)
    return out


def _structured_validation(raw: RawProvenance) -> dict[str, Any]:
    """Prefer the engine's structured results; otherwise synthesise them from the flat list
    with `classify_code` so both engine generations produce the same shape."""
    validation: dict[str, Any] = {
        "state": raw.validation_state,
        "source": "validation_results" if raw.validation_results else "validation_status",
        "active_manifest": _empty_families_full(),
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
            families[family].append(code)
    return validation


def _trust_view(raw: RawProvenance) -> dict[str, Any]:
    """Outcome of the separate trust run, kept apart from integrity.

    Newer engines report a state (Trusted | Valid | Invalid); older ones only codes. The
    verdict is conservative: True needs an explicit trusted signal, False an explicit
    untrusted / expired / revoked one, anything else stays None (not established)."""
    view: dict[str, Any] = {
        "evaluated": raw.trust_evaluated,
        "mode": raw.trust_mode,
        "list_version": raw.trust_list_version,
        "state": raw.trust_state,
        "codes": [],
        "trusted": None,
    }
    if not raw.trust_evaluated:
        return view
    codes: list[str] = []
    for status in raw.trust_status[:MAX_CODES]:
        code = _str(status.get("code"), 120)
        if code and classify_code(code) == "trust" and code not in codes:
            codes.append(code)
    if raw.trust_results:
        block = raw.trust_results.get("activeManifest") or raw.trust_results.get("active_manifest")
        for family in ("success", "informational", "failure"):
            for entry in ((block or {}).get(family) or [])[:MAX_CODES]:
                code = _str(entry.get("code"), 120) if isinstance(entry, dict) else None
                if code and classify_code(code) == "trust" and code not in codes:
                    codes.append(code)
    view["codes"] = codes
    negative = {
        "signingCredential.untrusted",
        "signingCredential.expired",
        "signingCredential.revoked",
        "signingCredential.invalid",
    }
    if raw.trust_state == "Trusted" or "signingCredential.trusted" in codes:
        view["trusted"] = True
    elif any(c in negative for c in codes) or raw.trust_state == "Invalid":
        view["trusted"] = False
    return view


_INFO_SIZE_RE = re.compile(r"Manifest store size = (\d+)")
ACTION_LABELS = ("c2pa.actions", "c2pa.actions.v2")
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
    if "Validation issues" in text:
        out["issues"] = True
    m = _INFO_URI_RE.search(text)
    if m:
        out["provenance_uri_kind"] = _uri_kind(m.group(1).strip())
    return out


_INFO_URI_RE = re.compile(r"Provenance URI = (\S+)")


def _uri_kind(uri: str) -> str:
    if uri.startswith("self#jumbf"):
        return "embedded"
    if uri.startswith(("http://", "https://")):
        return "remote"
    return "other"


def normalize_provenance(raw: RawProvenance) -> NormalizedProvenance:
    n = NormalizedProvenance(
        engine=raw.engine, engine_version=raw.engine_version, has_c2pa=raw.present
    )
    n.warnings = list(raw.warnings)
    if not raw.present or not raw.summary:
        n.remote_manifest_host = raw.remote_manifest_host
        n.manifest_location = "remote" if raw.remote_manifest_host else "none"
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
        n.signer_common_name = _str(sig.get("common_name"))
        n.signature_alg = _str(sig.get("alg"))
        n.signed_at = _str(sig.get("time"))

    for assertion in (active.get("assertions") or [])[:MAX_ASSERTIONS]:
        if not isinstance(assertion, dict):
            continue
        label = _str(assertion.get("label"))
        if label:
            n.assertion_labels.append(label)
        data = assertion.get("data")
        if label in ACTION_LABELS and isinstance(data, dict):
            for action in (data.get("actions") or [])[:MAX_ACTIONS]:
                if isinstance(action, dict):
                    n.actions.append(
                        {
                            "action": _str(action.get("action")),
                            "when": _str(action.get("when")),
                            "software_agent": _agent_name(action.get("softwareAgent")),
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
    n.trust = _trust_view(raw)
    n.trusted = n.trust.get("trusted")
    # Newer engines list only problems in the flat status; fold the structured codes in so
    # `validation_codes` is the complete picture whatever the engine generation.
    for family in ("success", "informational", "trust", "identity", "failure"):
        for code in n.validation["active_manifest"].get(family) or []:
            if code not in n.validation_codes:
                n.validation_codes.append(code)
    n.info = _parse_info(raw.info)
    n.manifest_location = n.info.get("provenance_uri_kind") or "embedded"
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
        if n.manifest_location == "remote":
            notes.append(
                "The file references content credentials hosted elsewhere. Verixa does not "
                "fetch remote manifests, so nothing about them is asserted."
            )
            return notes
        notes.append(
            "No content credentials (C2PA) were found. This does not establish whether the "
            "file was edited, generated, or authentic; most images carry no credentials."
        )
        return notes
    notes.append(
        "A valid signature shows the manifest is intact and was signed with the named "
        "certificate. It does not prove the claims are true."
    )
    trust = n.trust or {}
    if trust.get("evaluated"):
        listed = f"{trust.get('mode') or 'configured'} trust list"
        version = trust.get("list_version")
        listed += f" (version {version})" if version else ""
        if n.trusted is True:
            notes.append(
                f"The signing certificate chains to an anchor on the {listed}: the signer is a "
                "known conformance-program participant. Trust says who signed, not that the "
                "claims are true."
            )
        elif n.trusted is False:
            notes.append(
                f"The signing certificate is not on the {listed}; 'signer' is the certificate's "
                "stated issuer, not a verified identity. Many legitimate tools are not listed."
            )
        else:
            notes.append(
                f"The trust run against the {listed} was inconclusive; 'signer' is the "
                "certificate's stated issuer, not a verified identity."
            )
    else:
        notes.append(
            "Issuer trust (certificate chain against a trust list) was not evaluated for this "
            "analysis; 'signer' is the certificate's stated issuer, not a verified identity."
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
