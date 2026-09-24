"""Deeper reading of a C2PA manifest store: assertions, ingredient tree, manifest chain.

Everything here is *what the signer declared*, extracted verbatim and capped; nothing is
judged. Levels for these observations are assigned in ``services/evidence/engine.py``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.services.image.lineage import short_source_type
from app.utils.timeparse import as_utc, parse_timestamp

MAX_INGREDIENT_NODES = 200
MAX_INGREDIENT_DEPTH = 8
MAX_EXCLUSIONS = 50
MAX_SOURCE_TYPES = 50
MAX_AGENTS = 50
MAX_ENTRIES = 50

# Actions carry a signed digital source type in v1 (`digitalSourceType`) and v2 assertions.
ACTION_LABELS = ("c2pa.actions", "c2pa.actions.v2")
TRAINING_LABELS = ("c2pa.training-mining", "cawg.training-mining")
IDENTITY_LABELS = ("cawg.identity",)
HASH_LABELS = ("c2pa.hash.data", "c2pa.hash.boxes", "c2pa.hash.bmff", "c2pa.hash.bmff.v2")


@dataclass
class ManifestDepth:
    """Result of :func:`read_depth`; merged into ``NormalizedProvenance`` by the normaliser."""

    assertions: dict[str, Any] = field(default_factory=dict)
    software_agents: list[dict[str, Any]] = field(default_factory=list)
    ingredients: list[dict[str, Any]] = field(default_factory=list)
    ingredient_failures: int = 0
    manifest_chain: list[dict[str, Any]] = field(default_factory=list)
    manifest_order_conflict: bool = False


def _s(value: Any, limit: int = 300) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text[:limit] or None


def _agent(value: Any) -> dict[str, Any] | None:
    """`softwareAgent` is a string in v1 and an object ({name, version, ...}) in v2."""
    if isinstance(value, dict):
        name = _s(value.get("name"), 200)
        if not name:
            return None
        return {"name": name, "version": _s(value.get("version"), 80)}
    text = _s(value, 200)
    return {"name": text, "version": None} if text else None


def _hash_data(label: str, data: Any) -> dict[str, Any] | None:
    if not isinstance(data, dict):
        return None
    exclusions = []
    for ex in (data.get("exclusions") or [])[:MAX_EXCLUSIONS]:
        if isinstance(ex, dict) and isinstance(ex.get("start"), int):
            exclusions.append({"start": ex.get("start"), "length": ex.get("length")})
    return {
        "label": label,
        "alg": _s(data.get("alg"), 40),
        "name": _s(data.get("name"), 120),
        "exclusion_count": len(data.get("exclusions") or []),
        "exclusions": exclusions,
    }


def _training_mining(data: Any) -> dict[str, str] | None:
    if not isinstance(data, dict):
        return None
    entries = data.get("entries")
    if not isinstance(entries, dict):
        return None
    out: dict[str, str] = {}
    for key, value in list(entries.items())[:MAX_ENTRIES]:
        use = value.get("use") if isinstance(value, dict) else value
        k, u = _s(key, 80), _s(use, 40)
        if k and u:
            out[k] = u
    return out or None


def _identity(data: Any) -> dict[str, Any]:
    """Only presence and non-sensitive descriptors: the engine validates the credential."""
    out: dict[str, Any] = {"present": True, "kind": None, "names": []}
    if not isinstance(data, dict):
        return out
    payload = data.get("signer_payload") or {}
    sig_type = data.get("signature_type") or data.get("sig_type")
    out["kind"] = _s(sig_type, 80)
    credential = data.get("credential") or data.get("verifiedIdentities") or []
    names: list[str] = []
    for entry in credential if isinstance(credential, list) else []:
        if isinstance(entry, dict):
            name = _s(entry.get("name") or entry.get("username") or entry.get("type"), 120)
            if name:
                names.append(name)
    out["names"] = names[:10]
    referenced = payload.get("referenced_assertions") if isinstance(payload, dict) else None
    out["referenced_assertions"] = len(referenced) if isinstance(referenced, list) else 0
    return out


def read_assertions(
    active: dict[str, Any], detailed_manifest: dict[str, Any] | None
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Signed declarations from the active manifest (summary), plus the hash assertion which
    only the detailed `assertion_store` carries."""
    assertions: dict[str, Any] = {}
    agents: list[dict[str, Any]] = []
    source_types: list[dict[str, Any]] = []
    seen_agents: set[tuple[str, str | None]] = set()

    def add_agent(value: Any, origin: str) -> None:
        agent = _agent(value)
        if (
            agent
            and (agent["name"], agent["version"]) not in seen_agents
            and len(agents) < MAX_AGENTS
        ):
            seen_agents.add((agent["name"], agent["version"]))
            agents.append({**agent, "origin": origin})

    for assertion in active.get("assertions") or []:
        if not isinstance(assertion, dict):
            continue
        label = _s(assertion.get("label"), 120) or ""
        data = assertion.get("data")
        if label in ACTION_LABELS and isinstance(data, dict):
            for action in data.get("actions") or []:
                if not isinstance(action, dict):
                    continue
                add_agent(action.get("softwareAgent"), "action")
                uri = _s(action.get("digitalSourceType"), 200)
                if uri and len(source_types) < MAX_SOURCE_TYPES:
                    source_types.append(
                        {
                            "action": _s(action.get("action"), 80),
                            "uri": uri,
                            "short": short_source_type(uri),
                        }
                    )
            for template in data.get("templates") or []:
                if isinstance(template, dict):
                    add_agent(template.get("softwareAgent"), "template")
        elif label in TRAINING_LABELS:
            tm = _training_mining(data)
            if tm:
                assertions["training_mining"] = tm
        elif label in IDENTITY_LABELS:
            assertions["identity"] = _identity(data)
        elif label in HASH_LABELS:
            hd = _hash_data(label, data)
            if hd:
                assertions["hash_data"] = hd

    info = active.get("claim_generator_info")
    if isinstance(info, list):
        for entry in info:
            if isinstance(entry, dict):
                add_agent(entry, "claim_generator_info")

    if "hash_data" not in assertions and isinstance(detailed_manifest, dict):
        store = detailed_manifest.get("assertion_store")
        if isinstance(store, dict):
            for label in HASH_LABELS:
                hd = _hash_data(label, store.get(label))
                if hd:
                    assertions["hash_data"] = hd
                    break
    if source_types:
        assertions["source_types"] = source_types
    return assertions, agents


def _ingredient_node(
    ing: dict[str, Any],
    manifests: dict[str, Any],
    *,
    depth: int,
    budget: list[int],
    classify: Callable[[str], str],
) -> dict[str, Any]:
    codes: list[str] = []
    failures: list[str] = []
    for status in ing.get("validation_status") or []:
        code = _s(status.get("code"), 120) if isinstance(status, dict) else None
        if not code:
            continue
        codes.append(code)
    results = ing.get("validation_results")
    if isinstance(results, dict):
        for family in ("success", "informational", "failure"):
            block = (results.get("activeManifest") or results).get(family) or []
            for entry in block:
                code = _s(entry.get("code"), 120) if isinstance(entry, dict) else None
                if code:
                    codes.append(code)
                    if family == "failure":
                        failures.append(code)
    failures.extend(c for c in codes if c not in failures and classify(c) == "integrity")
    thumb = ing.get("thumbnail")
    label = _s(ing.get("active_manifest") or ing.get("manifest_label") or ing.get("label"), 200)
    node: dict[str, Any] = {
        "title": _s(ing.get("title"), 200),
        "format": _s(ing.get("format"), 80),
        "relationship": _s(ing.get("relationship"), 40),
        "document_id": _s(ing.get("document_id") or ing.get("documentID"), 200),
        "instance_id": _s(ing.get("instance_id") or ing.get("instanceID"), 200),
        "manifest_label": label,
        "validation_codes": codes[:50],
        "failure_codes": failures[:20],
        "thumbnail_identifier": _s(thumb.get("identifier"), 300)
        if isinstance(thumb, dict)
        else None,
        "children": [],
    }
    if label and depth < MAX_INGREDIENT_DEPTH:
        child_manifest = manifests.get(label)
        if isinstance(child_manifest, dict):
            for child in child_manifest.get("ingredients") or []:
                if budget[0] <= 0:
                    break
                if isinstance(child, dict):
                    budget[0] -= 1
                    node["children"].append(
                        _ingredient_node(
                            child, manifests, depth=depth + 1, budget=budget, classify=classify
                        )
                    )
    return node


def read_ingredients(
    active: dict[str, Any], manifests: dict[str, Any], classify: Callable[[str], str]
) -> tuple[list[dict[str, Any]], int]:
    budget = [MAX_INGREDIENT_NODES]
    nodes: list[dict[str, Any]] = []
    for ing in active.get("ingredients") or []:
        if budget[0] <= 0:
            break
        if isinstance(ing, dict):
            budget[0] -= 1
            nodes.append(
                _ingredient_node(ing, manifests, depth=1, budget=budget, classify=classify)
            )

    def count_failures(items: list[dict[str, Any]]) -> int:
        return sum((1 if n["failure_codes"] else 0) + count_failures(n["children"]) for n in items)

    return nodes, count_failures(nodes)


def read_manifest_chain(
    active_label: str | None, manifests: dict[str, Any], tolerance_seconds: float = 60.0
) -> tuple[list[dict[str, Any]], bool]:
    """Manifests in the store, active first, then each ingredient's manifest (breadth-first).
    A conflict is a manifest whose signing time is *earlier* than one of its ingredients'."""
    chain: list[dict[str, Any]] = []
    seen: set[str] = set()
    queue: list[tuple[str | None, str | None]] = [(active_label, None)]
    conflict = False
    while queue and len(chain) < MAX_INGREDIENT_NODES:
        label, parent = queue.pop(0)
        if not label or label in seen:
            continue
        manifest = manifests.get(label)
        if not isinstance(manifest, dict):
            continue
        seen.add(label)
        sig = manifest.get("signature_info") or {}
        signed_at = _s(sig.get("time"), 64) if isinstance(sig, dict) else None
        chain.append(
            {
                "label": label[:200],
                "parent": parent[:200] if parent else None,
                "signed_at": signed_at,
                "claim_generator": _s(manifest.get("claim_generator"), 200),
                "signer": _s(sig.get("issuer"), 200) if isinstance(sig, dict) else None,
            }
        )
        for ing in manifest.get("ingredients") or []:
            if isinstance(ing, dict):
                queue.append((_s(ing.get("active_manifest"), 200), label))
    by_label = {m["label"]: m for m in chain}
    for m in chain:
        parent_entry = by_label.get(m["parent"] or "")
        if not parent_entry:
            continue
        child_dt, _ = parse_timestamp(m["signed_at"])
        parent_dt, _ = parse_timestamp(parent_entry["signed_at"])
        if child_dt is None or parent_dt is None:
            continue
        if (as_utc(child_dt) - as_utc(parent_dt)).total_seconds() > tolerance_seconds:
            conflict = True
            m["signed_after_parent"] = True
    return chain, conflict


def read_depth(
    summary: dict[str, Any],
    detailed: dict[str, Any] | None,
    active_label: str | None,
    classify: Callable[[str], str],
) -> ManifestDepth:
    manifests = summary.get("manifests") or {}
    if not isinstance(manifests, dict):
        return ManifestDepth()
    active = manifests.get(active_label) if active_label else None
    if not isinstance(active, dict):
        active = next((m for m in manifests.values() if isinstance(m, dict)), {})
    detailed_manifest = None
    if isinstance(detailed, dict):
        dm = (detailed.get("manifests") or {}).get(active_label) if active_label else None
        detailed_manifest = dm if isinstance(dm, dict) else None
    assertions, agents = read_assertions(active, detailed_manifest)
    ingredients, failures = read_ingredients(active, manifests, classify)
    chain, conflict = read_manifest_chain(active_label, manifests)
    return ManifestDepth(
        assertions=assertions,
        software_agents=agents,
        ingredients=ingredients,
        ingredient_failures=failures,
        manifest_chain=chain,
        manifest_order_conflict=conflict,
    )
