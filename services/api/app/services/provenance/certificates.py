"""Reads the signing certificate chain of a C2PA manifest (public certificates only).

Pure parsing: who the certificate names, who issued it, when it is valid, what key it
carries. Nothing here decides trust (that is the engine's trust run) or assigns a level.
Certificates are public by design; the PEM itself stays in the raw row, summaries are capped.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import dsa, ec, ed448, ed25519, rsa
from cryptography.x509.oid import NameOID

from app.utils.timeparse import as_utc, parse_timestamp

MAX_PEM_BYTES = 64 * 1024
MAX_CERTIFICATES = 10
_BEGIN = "-----BEGIN CERTIFICATE-----"
_END = "-----END CERTIFICATE-----"


@dataclass(frozen=True)
class CertificateSummary:
    subject_common_name: str | None
    subject_organization: str | None
    subject_organizational_unit: str | None
    subject_country: str | None
    issuer_common_name: str | None
    issuer_organization: str | None
    serial_number: str  # hex, as certificate tools print it
    not_before: str  # ISO 8601 UTC
    not_after: str
    key_algorithm: str  # e.g. "RSA 2048", "EC secp256r1", "Ed25519"
    signature_algorithm: str | None
    self_signed: bool
    is_ca: bool | None
    sha256_fingerprint: str

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


def split_pem(pem: str) -> list[str]:
    """Individual PEM blocks, in the order given (leaf first for c2patool --certs)."""
    blocks: list[str] = []
    text = pem[:MAX_PEM_BYTES]
    start = text.find(_BEGIN)
    while start != -1 and len(blocks) < MAX_CERTIFICATES:
        end = text.find(_END, start)
        if end == -1:
            break
        blocks.append(text[start : end + len(_END)] + "\n")
        start = text.find(_BEGIN, end)
    return blocks


def _name(name: x509.Name, oid: x509.ObjectIdentifier, limit: int = 200) -> str | None:
    values = name.get_attributes_for_oid(oid)
    if not values:
        return None
    value = values[0].value
    text = value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)
    return text.strip()[:limit] or None


def _key_algorithm(cert: x509.Certificate) -> str:
    key = cert.public_key()
    if isinstance(key, rsa.RSAPublicKey):
        return f"RSA {key.key_size}"
    if isinstance(key, ec.EllipticCurvePublicKey):
        return f"EC {key.curve.name}"
    if isinstance(key, ed25519.Ed25519PublicKey):
        return "Ed25519"
    if isinstance(key, ed448.Ed448PublicKey):
        return "Ed448"
    if isinstance(key, dsa.DSAPublicKey):
        return f"DSA {key.key_size}"
    return type(key).__name__


def _is_ca(cert: x509.Certificate) -> bool | None:
    try:
        ext = cert.extensions.get_extension_for_class(x509.BasicConstraints)
    except x509.ExtensionNotFound:
        return None
    return bool(ext.value.ca)


def summarize(cert: x509.Certificate) -> CertificateSummary:
    try:
        sig_alg = cert.signature_algorithm_oid._name  # e.g. "sha256WithRSAEncryption"
    except Exception:
        sig_alg = None
    return CertificateSummary(
        subject_common_name=_name(cert.subject, NameOID.COMMON_NAME),
        subject_organization=_name(cert.subject, NameOID.ORGANIZATION_NAME),
        subject_organizational_unit=_name(cert.subject, NameOID.ORGANIZATIONAL_UNIT_NAME),
        subject_country=_name(cert.subject, NameOID.COUNTRY_NAME, 8),
        issuer_common_name=_name(cert.issuer, NameOID.COMMON_NAME),
        issuer_organization=_name(cert.issuer, NameOID.ORGANIZATION_NAME),
        serial_number=format(cert.serial_number, "x"),
        not_before=cert.not_valid_before_utc.isoformat(),
        not_after=cert.not_valid_after_utc.isoformat(),
        key_algorithm=_key_algorithm(cert),
        signature_algorithm=str(sig_alg)[:80] if sig_alg else None,
        self_signed=cert.subject == cert.issuer,
        is_ca=_is_ca(cert),
        sha256_fingerprint=cert.fingerprint(hashes.SHA256()).hex(),
    )


def parse_chain(pem: str | None) -> list[CertificateSummary]:
    """Summaries for every certificate that parses; a damaged block is skipped, not fatal."""
    if not pem:
        return []
    out: list[CertificateSummary] = []
    for block in split_pem(pem):
        try:
            cert = x509.load_pem_x509_certificate(block.encode("ascii", "ignore"))
        except ValueError:
            continue
        out.append(summarize(cert))
    return out


def validity_at(leaf: CertificateSummary, moment: str | datetime | None) -> bool | None:
    """Was the certificate inside its validity window at ``moment``?

    None when the moment is missing or unparseable: nothing is inferred. A moment without a
    timezone is treated as UTC (the manifest's signing time is normally RFC 3339 with one)."""
    if moment is None:
        return None
    when = moment if isinstance(moment, datetime) else parse_timestamp(moment)[0]
    if when is None:
        return None
    at = as_utc(when)
    start = datetime.fromisoformat(leaf.not_before).astimezone(UTC)
    end = datetime.fromisoformat(leaf.not_after).astimezone(UTC)
    return start <= at <= end


def certificate_view(pem: str | None, signed_at: str | None) -> dict[str, Any]:
    """The normalised `certificate` block: leaf, chain, and validity at the signing time."""
    chain = parse_chain(pem)
    if not chain:
        return {}
    leaf = chain[0]
    return {
        "leaf": leaf.to_json(),
        "chain_length": len(chain),
        "chain": [
            {
                "subject_common_name": c.subject_common_name,
                "subject_organization": c.subject_organization,
                "issuer_common_name": c.issuer_common_name,
                "not_after": c.not_after,
                "self_signed": c.self_signed,
                "is_ca": c.is_ca,
            }
            for c in chain
        ],
        "valid_at_signing": validity_at(leaf, signed_at),
    }
