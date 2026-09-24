"""Refresh the bundled C2PA trust list (development-time tool, never run by the service).

    python scripts/refresh_trust_list.py            # fetch the official list, rewrite the bundle
    python scripts/refresh_trust_list.py --check    # exit 1 when the bundle is stale

The bundle lives in ``app/providers/provenance/trust/`` next to a ``.meta.json`` that records
the source URL, the fetch time and the SHA-256 of the PEM. Reports show ``sha256[:12]`` as the
trust-list version. The download goes through the same outbound policy as every provider call,
with the host passed explicitly, so a changed URL cannot silently point elsewhere.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.utils.urlpolicy import assert_outbound_allowed  # noqa: E402

OFFICIAL_URL = (
    "https://raw.githubusercontent.com/c2pa-org/conformance-public/refs/heads/main/"
    "trust-list/C2PA-TRUST-LIST.pem"
)
ALLOWED_HOSTS = ["raw.githubusercontent.com"]
TRUST_DIR = Path(__file__).resolve().parents[1] / "app" / "providers" / "provenance" / "trust"
PEM_PATH = TRUST_DIR / "C2PA-TRUST-LIST.pem"
META_PATH = TRUST_DIR / "C2PA-TRUST-LIST.meta.json"
MAX_BYTES = 2 * 1024 * 1024


def fetch_trust_list(url: str = OFFICIAL_URL, *, allowed_hosts: list[str] | None = None) -> str:
    """PEM text of the trust list at ``url``; refuses hosts outside the allowlist."""
    assert_outbound_allowed(url, allowed_hosts=allowed_hosts or ALLOWED_HOSTS)
    with httpx.Client(timeout=30, follow_redirects=False) as client:
        response = client.get(url)
    response.raise_for_status()
    text = response.text
    if len(text) > MAX_BYTES or "-----BEGIN CERTIFICATE-----" not in text:
        raise ValueError("the downloaded file is not a PEM certificate list")
    return text


def list_version(pem: str) -> str:
    return hashlib.sha256(pem.encode("utf-8")).hexdigest()[:12]


def write_bundle(pem: str, *, url: str = OFFICIAL_URL) -> dict[str, object]:
    TRUST_DIR.mkdir(parents=True, exist_ok=True)
    PEM_PATH.write_text(pem, encoding="utf-8", newline="\n")
    meta: dict[str, object] = {
        "source_url": url,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "sha256": hashlib.sha256(pem.encode("utf-8")).hexdigest(),
        "certificates": pem.count("-----BEGIN CERTIFICATE-----"),
    }
    META_PATH.write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8", newline="\n")
    return meta


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only report whether the bundle is stale")
    args = parser.parse_args(argv)
    pem = fetch_trust_list()
    fresh = hashlib.sha256(pem.encode("utf-8")).hexdigest()
    current = json.loads(META_PATH.read_text("utf-8")).get("sha256") if META_PATH.exists() else None
    if args.check:
        if current == fresh:
            print(f"bundle is current (version {fresh[:12]})")
            return 0
        print(f"bundle is stale: bundled {str(current)[:12]} vs upstream {fresh[:12]}")
        return 1
    meta = write_bundle(pem)
    print(f"wrote {PEM_PATH.name}: {meta['certificates']} certificates, version {fresh[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
