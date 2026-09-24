import hashlib
import io
import struct
import zlib
from typing import Any

import pytest
from httpx import AsyncClient
from PIL import Image

from app.providers.search.mock import _bucket
from app.services.image import InvalidImageError, validate_image
from tests.test_auth import bearer, login, register

Json = dict[str, Any]
MAX_BYTES = 25 * 1024 * 1024
MAX_PIXELS = 40_000_000


def make_image(fmt: str, size: tuple[int, int] = (64, 48), mode: str = "RGB") -> bytes:
    buf = io.BytesIO()
    Image.new(mode, size, color=(200, 30, 30) if mode == "RGB" else 128).save(buf, format=fmt)
    return buf.getvalue()


def image_with_mock_search_hits(fmt: str) -> bytes:
    """An image whose bytes make the mock search provider return at least one hit.

    The mock buckets on the encoded bytes, and encoders differ between platforms, so a
    fixed picture cannot be relied on; vary one channel until the bucket is non-zero.
    """
    for shade in range(256):
        buf = io.BytesIO()
        Image.new("RGB", (64, 48), color=(200, 30, shade)).save(buf, format=fmt)
        data = buf.getvalue()
        if _bucket(data, 3):
            return data
    raise AssertionError("no payload produced a mock search hit")


def png_with_declared_size(width: int, height: int) -> bytes:
    """A syntactically valid PNG header claiming huge dimensions (decompression-bomb shape)."""

    def chunk(tag: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body))
            + tag
            + body
            + struct.pack(">I", zlib.crc32(tag + body) & 0xFFFFFFFF)
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(b"\x00"))
        + chunk(b"IEND", b"")
    )


async def auth_headers(client: AsyncClient, email: str = "up@example.com") -> dict[str, str]:
    await register(client, email=email)
    return bearer(await login(client, email=email))


# -- validation unit tests --------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "mime", "ext"),
    [
        ("JPEG", "image/jpeg", "jpg"),
        ("PNG", "image/png", "png"),
        ("WEBP", "image/webp", "webp"),
        ("TIFF", "image/tiff", "tiff"),
    ],
)
def test_validate_supported_formats(fmt: str, mime: str, ext: str) -> None:
    data = make_image(fmt)
    v = validate_image(data, max_bytes=MAX_BYTES, max_pixels=MAX_PIXELS)
    assert (v.mime_type, v.extension, v.pil_format) == (mime, ext, fmt)
    assert (v.width, v.height) == (64, 48)
    assert v.sha256 == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    "data",
    [
        b"",
        b"GIF89a" + b"\x00" * 64,  # unsupported format
        b"%PDF-1.7 not an image",
        b"\xff\xd8\xff" + b"\x00" * 32,  # JPEG magic but garbage body
        make_image("PNG")[:40],  # truncated
    ],
)
def test_validate_rejects_non_images(data: bytes) -> None:
    with pytest.raises(InvalidImageError):
        validate_image(data, max_bytes=MAX_BYTES, max_pixels=MAX_PIXELS)


def test_validate_rejects_decompression_bomb_by_header() -> None:
    with pytest.raises(InvalidImageError, match="too large to analyse"):
        validate_image(
            png_with_declared_size(60_000, 60_000), max_bytes=MAX_BYTES, max_pixels=MAX_PIXELS
        )


def test_validate_enforces_size_cap() -> None:
    data = make_image("PNG")
    with pytest.raises(Exception) as exc:
        validate_image(data, max_bytes=len(data) - 1, max_pixels=MAX_PIXELS)
    assert getattr(exc.value, "code", "") == "PAYLOAD_TOO_LARGE"


# -- API ----------------------------------------------------------------------------


async def test_upload_creates_analysis_and_stores_original(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    data = make_image("JPEG", (120, 80))
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("holiday.JPG", data, "application/octet-stream")},
        data={"title": "  Beach  "},
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["status"] == "queued" and body["type"] == "image"

    r = await client.get(f"/analysis/{body['id']}", headers=headers)
    detail = r.json()
    assert detail["title"] == "Beach"
    assert detail["file"] == {
        "original_filename": "holiday.JPG",
        "mime_type": "image/jpeg",  # from content, not the client's octet-stream
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "width": 120,
        "height": 80,
    }
    assert "object_key" not in detail["file"]

    storage = client._transport.app.state.storage  # type: ignore[attr-defined]
    stored, content_type = await storage.get(
        f"uploads/{await _user_id(client, headers)}/{body['id']}/{detail['file']['sha256']}.jpg"
    )
    assert stored == data and content_type == "image/jpeg"


async def test_upload_title_defaults_to_filename(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("../evil\\name.png", make_image("PNG"), "image/png")},
    )
    assert r.status_code == 201
    detail = (await client.get(f"/analysis/{r.json()['id']}", headers=headers)).json()
    assert detail["title"] == "name.png"  # basename only: directories and dot-prefixes dropped
    assert detail["file"]["original_filename"] == "name.png"


async def test_upload_rejects_non_image_without_creating_record(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("x.jpg", b"not really a jpeg", "image/jpeg")},
    )
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "INVALID_FILE"
    assert (await client.get("/analysis/counts", headers=headers)).json()["total"] == 0


async def test_upload_rejects_oversized(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    big = make_image("PNG") + b"\x00" * (2 * 1024 * 1024)
    r = await client.post(
        "/analysis/image", headers=headers, files={"file": ("big.png", big, "image/png")}
    )
    assert r.status_code == 413
    assert r.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"


async def test_upload_requires_auth_and_file(client: AsyncClient) -> None:
    assert (
        await client.post(
            "/analysis/image", files={"file": ("a.png", make_image("PNG"), "image/png")}
        )
    ).status_code == 401
    headers = await auth_headers(client)
    r = await client.post("/analysis/image", headers=headers, data={"title": "no file"})
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_upload_is_listed_and_deletable(client: AsyncClient) -> None:
    headers = await auth_headers(client)
    r = await client.post(
        "/analysis/image",
        headers=headers,
        files={"file": ("a.webp", make_image("WEBP"), "image/webp")},
    )
    analysis_id = r.json()["id"]
    items = (await client.get("/analysis", headers=headers)).json()["items"]
    assert items[0]["id"] == analysis_id and items[0]["file"]["mime_type"] == "image/webp"

    assert (await client.delete(f"/analysis/{analysis_id}", headers=headers)).status_code == 204
    storage = client._transport.app.state.storage  # type: ignore[attr-defined]
    uid = await _user_id(client, headers)
    assert not await storage.exists(
        f"uploads/{uid}/{analysis_id}/{items[0]['file']['sha256']}.webp"
    )


async def _user_id(client: AsyncClient, headers: dict[str, str]) -> str:
    me = await client.get("/auth/me", headers=headers)
    return str(me.json()["id"])
