"""Untrusted-upload validation for images.

Never trusts the filename or client MIME type: the format comes from magic bytes
and Pillow's decoder. Dimensions are checked from the header before any pixel
data is decoded to defend against decompression bombs.
"""

import hashlib
import io
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError

from app.utils.errors import AppError


class InvalidImageError(AppError):
    status_code = 422
    code = "INVALID_FILE"


class ImageTooLargeError(AppError):
    status_code = 413
    code = "PAYLOAD_TOO_LARGE"


# Pillow format name -> (canonical MIME, canonical extension)
SUPPORTED_FORMATS: dict[str, tuple[str, str]] = {
    "JPEG": ("image/jpeg", "jpg"),
    "PNG": ("image/png", "png"),
    "WEBP": ("image/webp", "webp"),
    "TIFF": ("image/tiff", "tiff"),
}
SUPPORTED_MIME_TYPES = frozenset(m for m, _ in SUPPORTED_FORMATS.values())

_MAGIC: tuple[tuple[bytes, str], ...] = (
    (b"\xff\xd8\xff", "JPEG"),
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"II*\x00", "TIFF"),
    (b"MM\x00*", "TIFF"),
)


@dataclass(frozen=True)
class ValidatedImage:
    data: bytes
    sha256: str
    mime_type: str
    extension: str
    pil_format: str
    width: int
    height: int
    frames: int = 1

    @property
    def size_bytes(self) -> int:
        return len(self.data)


def sniff_format(data: bytes) -> str | None:
    """Format from magic bytes only; None if not a supported image signature."""
    for magic, fmt in _MAGIC:
        if data.startswith(magic):
            return fmt
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "WEBP"
    return None


def validate_image(data: bytes, *, max_bytes: int, max_pixels: int) -> ValidatedImage:
    if len(data) == 0:
        raise InvalidImageError("The uploaded file is empty.")
    if len(data) > max_bytes:
        raise ImageTooLargeError(
            f"The file exceeds the maximum upload size of {max_bytes // (1024 * 1024)} MB."
        )

    sniffed = sniff_format(data)
    if sniffed is None:
        raise InvalidImageError(
            "The uploaded file is not a supported image (JPEG, PNG, WebP, TIFF)."
        )

    # Header-only open: no pixel decoding yet, so dimension checks are cheap and safe.
    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = img.format or ""
            width, height = img.size
            if fmt != sniffed or fmt not in SUPPORTED_FORMATS:
                raise InvalidImageError("The file signature does not match its image format.")
            if width <= 0 or height <= 0:
                raise InvalidImageError("The image has invalid dimensions.")
            if width * height > max_pixels:
                raise InvalidImageError(
                    f"The image is too large to analyse ({width}x{height}); "
                    f"the limit is {max_pixels // 1_000_000} megapixels."
                )
            # Full integrity pass over the encoded data (does not decode pixels for JPEG/PNG).
            img.verify()
    except Image.DecompressionBombError as exc:
        # Pillow's own guard fires inside open() for absurd headers; same outcome as ours.
        raise InvalidImageError(
            f"The image is too large to analyse; the limit is {max_pixels // 1_000_000} megapixels."
        ) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise InvalidImageError("The uploaded image is malformed or truncated.") from exc

    # verify() invalidates the handle; decode once to ensure pixels are actually readable.
    frames = 1
    try:
        with Image.open(io.BytesIO(data)) as img:
            img.load()
            frames = max(1, int(getattr(img, "n_frames", 1)))
    except (OSError, SyntaxError, ValueError, Image.DecompressionBombError) as exc:
        raise InvalidImageError("The uploaded image could not be decoded.") from exc

    mime, ext = SUPPORTED_FORMATS[fmt]
    return ValidatedImage(
        data=data,
        sha256=hashlib.sha256(data).hexdigest(),
        mime_type=mime,
        extension=ext,
        pil_format=fmt,
        width=width,
        height=height,
        frames=frames,
    )
