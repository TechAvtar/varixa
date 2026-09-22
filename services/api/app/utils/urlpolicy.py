"""Outbound URL policy (SSRF guard, docs/09) and link hygiene. Pure; no network access.

Verixa never fetches URLs that users supply. The only outbound HTTP calls are provider
adapters, whose endpoints come from configuration and must pass ``assert_outbound_allowed``
against an explicit host allowlist. URLs that *providers* return are stored and shown as
links only; ``is_web_url`` keeps anything that is not plain http(s) out of the UI.
"""

import ipaddress
from collections.abc import Iterable
from urllib.parse import urlsplit

_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


class DisallowedUrlError(ValueError):
    """The URL is outside the outbound policy. The message never echoes credentials."""


def is_web_url(url: str) -> bool:
    """True for absolute http(s) URLs with a host; false for javascript:, data:, relative..."""
    try:
        parts = urlsplit(url.strip())
    except ValueError:
        return False
    return parts.scheme in ("http", "https") and bool(parts.hostname)


def _is_ip_literal(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return False
    return True


def host_allowed(host: str, allowed_hosts: Iterable[str]) -> bool:
    host = host.lower().rstrip(".")
    for allowed in allowed_hosts:
        a = allowed.strip().lower().rstrip(".")
        if a and (host == a or host.endswith("." + a)):
            return True
    return False


def assert_outbound_allowed(
    url: str, *, allowed_hosts: Iterable[str], allow_insecure_localhost: bool = False
) -> str:
    """Return ``url`` if a provider adapter may call it, else raise ``DisallowedUrlError``.

    Rules: https only (plain http solely to localhost when explicitly allowed, for local
    stubs), no credentials in the URL, no IP literals, and the host must be on the allowlist.
    """
    try:
        parts = urlsplit(url)
    except ValueError as exc:
        raise DisallowedUrlError("outbound URL is not parseable") from exc
    host = (parts.hostname or "").lower()
    if not host:
        raise DisallowedUrlError("outbound URL has no host")
    if parts.username or parts.password:
        raise DisallowedUrlError("outbound URL must not embed credentials")
    local = host in _LOCAL_HOSTS
    if parts.scheme != "https" and not (
        parts.scheme == "http" and local and allow_insecure_localhost
    ):
        raise DisallowedUrlError("outbound URL must use https")
    if _is_ip_literal(host) and not (local and allow_insecure_localhost):
        raise DisallowedUrlError("outbound URL must name a host, not an IP address")
    if not host_allowed(host, allowed_hosts) and not (local and allow_insecure_localhost):
        raise DisallowedUrlError(f"outbound host '{host}' is not on VERIXA_OUTBOUND_ALLOWED_HOSTS")
    return url
