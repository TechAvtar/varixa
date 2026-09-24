"""Object storage interface. Keys are opaque, internal, and never shown to clients."""

import re
from dataclasses import dataclass
from typing import Protocol

# Keys: path-like, ASCII, no leading slash, no "." or ".." segments, no backslashes.
_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")
MAX_KEY_LENGTH = 512


class InvalidKeyError(ValueError):
    pass


class ObjectNotFoundError(KeyError):
    pass


def validate_key(key: str) -> str:
    if not key or len(key) > MAX_KEY_LENGTH or not _KEY_RE.match(key):
        raise InvalidKeyError("invalid object key")
    if any(seg in {".", ".."} for seg in key.split("/")):
        raise InvalidKeyError("invalid object key")
    return key


@dataclass(frozen=True)
class StoredObject:
    key: str
    size_bytes: int
    content_type: str


class ObjectStorage(Protocol):
    async def put(self, key: str, data: bytes, *, content_type: str) -> StoredObject: ...

    async def get(self, key: str) -> tuple[bytes, str]:
        """Return (data, content_type). Raises ObjectNotFoundError."""
        ...

    async def exists(self, key: str) -> bool: ...

    async def probe(self) -> bool:
        """Readiness: True when the backend is reachable and writable. Never raises."""
        ...

    async def delete(self, key: str) -> None:
        """Idempotent: deleting a missing key is not an error."""
        ...

    async def signed_url(self, key: str, *, ttl_seconds: int, filename: str | None = None) -> str:
        """Short-lived URL granting read access to one object. Never log the result."""
        ...
