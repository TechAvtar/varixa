"""Near-duplicate discovery among a user's own analyses using stored fingerprints.

A match is a *similarity signal*: identical SHA-256 means identical bytes;
a small perceptual distance means the pictures look alike (crops, recompression,
resizes). Neither says which came first or where the image originated.
"""

from dataclasses import dataclass
from typing import Protocol

from app.services.image.hashing import hamming_distance


class FingerprintLike(Protocol):
    sha256: str
    phash: str
    dhash: str
    ahash: str


@dataclass(frozen=True)
class SimilarityMatch:
    relation: str  # "exact" | "near"
    sha256_match: bool
    phash_distance: int
    dhash_distance: int
    ahash_distance: int

    @property
    def score(self) -> int:
        """Lower is more similar; used only for ordering."""
        return 0 if self.sha256_match else self.phash_distance + self.dhash_distance


def compare(
    a: FingerprintLike, b: FingerprintLike, *, near_threshold: int
) -> SimilarityMatch | None:
    """Return a match when ``b`` is an exact or near duplicate of ``a``; else None.

    ``near_threshold`` is the maximum Hamming distance (0-64) on pHash *or* dHash
    that counts as "near". Kept configurable; 10 is a common, conservative default.
    """
    sha_match = a.sha256 == b.sha256
    p = hamming_distance(a.phash, b.phash)
    d = hamming_distance(a.dhash, b.dhash)
    h = hamming_distance(a.ahash, b.ahash)
    if sha_match:
        return SimilarityMatch("exact", True, p, d, h)
    if min(p, d) <= near_threshold:
        return SimilarityMatch("near", False, p, d, h)
    return None
