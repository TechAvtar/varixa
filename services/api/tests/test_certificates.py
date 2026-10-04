"""Signing certificate chain parsing (T048): summaries, validity at signing, robustness."""

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import NameOID

from app.services.provenance.certificates import (
    MAX_CERTIFICATES,
    certificate_view,
    parse_chain,
    split_pem,
    validity_at,
)

FIXTURES = Path(__file__).parent / "fixtures" / "c2pa"
SAMPLE_CHAIN = (FIXTURES / "sample_chain.pem").read_text("utf-8")


def make_cert(
    *,
    cn: str = "Test Signer",
    org: str | None = "Test Org",
    not_before: datetime,
    not_after: datetime,
    key: Any = None,
    ca: bool | None = False,
) -> str:
    key = key or ec.generate_private_key(ec.SECP256R1())
    attrs = [x509.NameAttribute(NameOID.COMMON_NAME, cn)]
    if org:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, org))
    name = x509.Name(attrs)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(0xABCDEF)
        .not_valid_before(not_before)
        .not_valid_after(not_after)
    )
    if ca is not None:
        builder = builder.add_extension(x509.BasicConstraints(ca=ca, path_length=None), True)
    cert = builder.sign(key, hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.PEM).decode("ascii")


def test_sample_chain_is_parsed_leaf_first() -> None:
    chain = parse_chain(SAMPLE_CHAIN)
    assert [c.subject_common_name for c in chain] == ["C2PA Signer", "Intermediate CA", "Root CA"]
    leaf = chain[0]
    assert leaf.subject_organization == "C2PA Test Signing Cert"
    assert leaf.issuer_common_name == "Intermediate CA"
    assert leaf.key_algorithm == "RSA 4096" and leaf.is_ca is False and not leaf.self_signed
    assert leaf.not_before.startswith("2022-06-10") and leaf.not_after.startswith("2030-08-26")
    assert len(leaf.sha256_fingerprint) == 64 and leaf.serial_number.startswith("7e3e629a")
    assert chain[2].self_signed and chain[2].is_ca is True


def test_certificate_view_reports_validity_at_signing() -> None:
    view = certificate_view(SAMPLE_CHAIN, "2022-08-19T19:03:41+00:00")
    assert view["valid_at_signing"] is True and view["chain_length"] == 3
    assert view["leaf"]["subject_common_name"] == "C2PA Signer"
    assert [c["self_signed"] for c in view["chain"]] == [False, False, True]
    assert certificate_view(SAMPLE_CHAIN, "2040-01-01T00:00:00Z")["valid_at_signing"] is False
    assert certificate_view(SAMPLE_CHAIN, "2000-01-01T00:00:00Z")["valid_at_signing"] is False
    assert certificate_view(SAMPLE_CHAIN, None)["valid_at_signing"] is None
    assert certificate_view(SAMPLE_CHAIN, "not a time")["valid_at_signing"] is None


def test_expired_certificate_at_signing() -> None:
    now = datetime.now(UTC)
    pem = make_cert(not_before=now - timedelta(days=400), not_after=now - timedelta(days=30))
    (leaf,) = parse_chain(pem)
    assert (
        leaf.key_algorithm == "EC secp256r1" and leaf.self_signed and leaf.serial_number == "abcdef"
    )
    assert validity_at(leaf, now) is False
    assert validity_at(leaf, now - timedelta(days=100)) is True
    # A naive time is read as UTC.
    assert validity_at(leaf, (now - timedelta(days=100)).replace(tzinfo=None).isoformat()) is True


def test_rsa_key_and_missing_extensions() -> None:
    now = datetime.now(UTC)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = make_cert(
        cn="RSA Signer", org=None, key=key, ca=None,
        not_before=now - timedelta(days=1), not_after=now + timedelta(days=1),
    )  # fmt: skip
    (leaf,) = parse_chain(pem)
    assert leaf.key_algorithm == "RSA 2048" and leaf.subject_organization is None
    assert leaf.is_ca is None  # no BasicConstraints extension


def test_damaged_and_oversized_input_is_tolerated() -> None:
    assert (
        parse_chain(None) == [] and parse_chain("") == [] and certificate_view("junk", None) == {}
    )
    broken = "-----BEGIN CERTIFICATE-----\nnot base64 at all\n-----END CERTIFICATE-----\n"
    good = parse_chain(SAMPLE_CHAIN)[0]
    chain = parse_chain(broken + SAMPLE_CHAIN)
    assert chain[0].sha256_fingerprint == good.sha256_fingerprint  # the damaged block is skipped
    assert parse_chain("-----BEGIN CERTIFICATE-----\nMA==\n") == []  # no END marker
    many = SAMPLE_CHAIN * 10
    assert len(split_pem(many)) <= MAX_CERTIFICATES


@pytest.mark.parametrize("moment", [None, "", "garbage"])
def test_validity_is_unknown_without_a_usable_time(moment: Any) -> None:
    leaf = parse_chain(SAMPLE_CHAIN)[0]
    assert validity_at(leaf, moment) is None
