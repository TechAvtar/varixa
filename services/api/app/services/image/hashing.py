"""Content and perceptual hashes. Pure, deterministic functions; no I/O.

- SHA-256 / MD5 identify the exact bytes (MD5 only for compatibility with
  external tooling; it is not used for integrity).
- aHash / dHash / pHash are 64-bit perceptual fingerprints of the decoded
  pixels: similar-looking images give hashes with a small Hamming distance.
  They are *signals* for near-duplicate discovery, never proof of provenance.

Algorithms follow the widely used definitions (Krawetz "Looks Like It" and the
imagehash library) so values are comparable with other tools:
  aHash: 8x8 grayscale, bit = pixel > mean
  dHash: 9x8 grayscale, bit = left pixel > right neighbour (row-wise)
  pHash: 32x32 grayscale, 2D DCT-II, top-left 8x8, bit = coefficient > median
Bits are packed row-major, MSB first, and rendered as 16 hex characters.
"""

import hashlib
import io
from dataclasses import dataclass

import numpy as np
from numpy.typing import NDArray
from PIL import Image

HASH_SIZE = 8
PHASH_INPUT = 32
_LANCZOS = Image.Resampling.LANCZOS


@dataclass(frozen=True)
class ImageHashes:
    sha256: str
    md5: str
    ahash: str
    dhash: str
    phash: str


# -- byte hashes -------------------------------------------------------------------


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def md5_hex(data: bytes) -> str:
    return hashlib.md5(data, usedforsecurity=False).hexdigest()


# -- perceptual hashes ---------------------------------------------------------------


def _grayscale(img: Image.Image, size: tuple[int, int]) -> NDArray[np.float64]:
    # First frame only for animated/multi-page inputs; alpha is dropped.
    gray = img.convert("L").resize(size, _LANCZOS)
    return np.asarray(gray, dtype=np.float64)


def _pack_bits(bits: NDArray[np.bool_]) -> str:
    flat = bits.flatten()
    value = 0
    for bit in flat:
        value = (value << 1) | int(bit)
    return f"{value:0{flat.size // 4}x}"


def average_hash(img: Image.Image) -> str:
    pixels = _grayscale(img, (HASH_SIZE, HASH_SIZE))
    return _pack_bits(pixels > pixels.mean())


def difference_hash(img: Image.Image) -> str:
    pixels = _grayscale(img, (HASH_SIZE + 1, HASH_SIZE))  # width 9, height 8
    return _pack_bits(pixels[:, :-1] > pixels[:, 1:])


def _dct_matrix(n: int) -> NDArray[np.float64]:
    """Orthonormal DCT-II basis (matches scipy.fft.dct(type=2, norm='ortho'))."""
    k = np.arange(n).reshape(-1, 1)
    i = np.arange(n).reshape(1, -1)
    m: NDArray[np.float64] = np.cos(np.pi * (2 * i + 1) * k / (2 * n)) * np.sqrt(2.0 / n)
    m[0, :] /= np.sqrt(2.0)
    return m


_DCT32 = _dct_matrix(PHASH_INPUT)


def perceptual_hash(img: Image.Image) -> str:
    pixels = _grayscale(img, (PHASH_INPUT, PHASH_INPUT))
    dct = _DCT32 @ pixels @ _DCT32.T
    low = dct[:HASH_SIZE, :HASH_SIZE]
    return _pack_bits(low > np.median(low))


# -- convenience ---------------------------------------------------------------------


def compute_hashes(data: bytes) -> ImageHashes:
    """All hashes for an already-validated image. Callers validate first."""
    with Image.open(io.BytesIO(data)) as img:
        img.load()
        return ImageHashes(
            sha256=sha256_hex(data),
            md5=md5_hex(data),
            ahash=average_hash(img),
            dhash=difference_hash(img),
            phash=perceptual_hash(img),
        )


def hamming_distance(a: str, b: str) -> int:
    """Bit difference between two hex hashes of equal length (0 = identical)."""
    if len(a) != len(b):
        raise ValueError("hashes must have equal length")
    return bin(int(a, 16) ^ int(b, 16)).count("1")
