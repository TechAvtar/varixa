"""Validation of an optional C2PA sidecar (.c2pa): a binary JUMBF manifest store.

Untrusted like every upload: the name and MIME type are ignored, only the bytes decide.
A sidecar is not interpreted here; c2patool validates it against the image it was sent with.
"""

import hashlib
from dataclasses import dataclass

from app.services.image.validation import ImageTooLargeError, InvalidImageError

SIDECAR_MIME = "application/c2pa"
_JUMBF_SUPERBOX = b"jumb"
_JUMBF_DESCRIPTION = b"jumd"
_MIN_BYTES = 64


class InvalidSidecarError(InvalidImageError):
    """422 INVALID_FILE: the sidecar is not a C2PA manifest store."""


@dataclass(frozen=True)
class ValidatedSidecar:
    data: bytes
    sha256: str

    @property
    def size_bytes(self) -> int:
        return len(self.data)


def validate_sidecar(data: bytes, *, max_bytes: int) -> ValidatedSidecar:
    if len(data) > max_bytes:
        raise ImageTooLargeError(f"The sidecar exceeds the maximum size of {max_bytes // 1024} KB.")
    # ISO BMFF box: 4-byte length, then the type "jumb"; its first child is a "jumd" box.
    if len(data) < _MIN_BYTES or data[4:8] != _JUMBF_SUPERBOX or data[12:16] != _JUMBF_DESCRIPTION:
        raise InvalidSidecarError(
            "The sidecar is not a C2PA manifest store (.c2pa). Remove it or choose another file."
        )
    return ValidatedSidecar(data=data, sha256=hashlib.sha256(data).hexdigest())
