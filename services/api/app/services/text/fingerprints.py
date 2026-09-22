"""Text fingerprints: exact, normalised, canonical hashes and a MinHash near-duplicate signature.

- ``sha256``            identity of the original bytes (as submitted)
- ``normalized_sha256`` identity of the normalised working copy
- ``canonical_sha256``  identity after case-folding, punctuation removal and whitespace
                        collapsing: catches retyped/reformatted copies of the same words
- ``minhash``           64 seeded min-hashes over word 5-gram shingles; the fraction of
                        equal positions estimates Jaccard similarity of two texts' shingle
                        sets. A signal for near-duplicate discovery, never proof of copying.

Everything is deterministic and pure (blake2b keyed hashing, no randomness).
"""

import hashlib
import re
import unicodedata
from dataclasses import dataclass

FINGERPRINT_VERSION = "v1"
SHINGLE_SIZE = 5
MINHASH_PERMUTATIONS = 64
_MERSENNE = (1 << 61) - 1
_MAX_HASH = 1 << 32
_EMPTY_SLOT = _MAX_HASH  # sentinel for texts with no shingles

_WORD_RE = re.compile(r"[^\W_]+", re.UNICODE)


@dataclass(frozen=True)
class TextFingerprints:
    sha256: str
    normalized_sha256: str
    canonical_sha256: str
    minhash: list[int]  # MINHASH_PERMUTATIONS ints, each < 2**32 (or _EMPTY_SLOT)
    shingle_count: int
    version: str = FINGERPRINT_VERSION


def canonical_form(text: str) -> str:
    """Case-folded words joined by single spaces; punctuation and formatting dropped."""
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(_WORD_RE.findall(folded))


def _shingles(words: list[str], size: int = SHINGLE_SIZE) -> set[str]:
    if len(words) < size:
        return {" ".join(words)} if words else set()
    return {" ".join(words[i : i + size]) for i in range(len(words) - size + 1)}


def _base_hash(shingle: str) -> int:
    return int.from_bytes(hashlib.blake2b(shingle.encode("utf-8"), digest_size=8).digest(), "big")


def _permutation_params(n: int) -> list[tuple[int, int]]:
    """Deterministic (a, b) pairs derived from a fixed key; a is non-zero."""
    params: list[tuple[int, int]] = []
    for i in range(n):
        seed = hashlib.blake2b(f"verixa-minhash-{i}".encode(), digest_size=16).digest()
        a = (int.from_bytes(seed[:8], "big") % (_MERSENNE - 1)) + 1
        b = int.from_bytes(seed[8:], "big") % _MERSENNE
        params.append((a, b))
    return params


_PARAMS = _permutation_params(MINHASH_PERMUTATIONS)


def minhash_signature(shingles: set[str]) -> list[int]:
    if not shingles:
        return [_EMPTY_SLOT] * MINHASH_PERMUTATIONS
    base = [_base_hash(s) for s in shingles]
    signature: list[int] = []
    for a, b in _PARAMS:
        signature.append(min(((a * h + b) % _MERSENNE) % _MAX_HASH for h in base))
    return signature


def estimate_jaccard(sig_a: list[int], sig_b: list[int]) -> float:
    """Fraction of matching positions; 0.0 when either text had no shingles."""
    if len(sig_a) != len(sig_b) or not sig_a:
        raise ValueError("signatures must have equal, non-zero length")
    if sig_a[0] == _EMPTY_SLOT or sig_b[0] == _EMPTY_SLOT:
        return 0.0
    return sum(1 for x, y in zip(sig_a, sig_b, strict=True) if x == y) / len(sig_a)


def compute_text_fingerprints(original: bytes | str, normalized: str) -> TextFingerprints:
    raw = original if isinstance(original, bytes) else original.encode("utf-8")
    canonical = canonical_form(normalized)
    words = canonical.split(" ") if canonical else []
    shingles = _shingles(words)
    return TextFingerprints(
        sha256=hashlib.sha256(raw).hexdigest(),
        normalized_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        canonical_sha256=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        minhash=minhash_signature(shingles),
        shingle_count=len(shingles),
    )
