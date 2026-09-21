import time
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
from httpx import AsyncClient

from app.providers.storage.base import InvalidKeyError, ObjectNotFoundError, validate_key
from app.providers.storage.local import LocalObjectStorage
from app.providers.storage.s3 import S3ObjectStorage
from app.services import storage_keys

SECRET = "unit-test-secret-of-sufficient-length-0000"


@pytest.fixture
def local(tmp_path: Path) -> LocalObjectStorage:
    return LocalObjectStorage(
        root=tmp_path / "store", secret=SECRET, public_base_url="http://api.test/"
    )


# -- key validation -------------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    ["uploads/u/a/abc.jpg", "a", "reports/x-y_z.1/file.pdf"],
)
def test_valid_keys(key: str) -> None:
    assert validate_key(key) == key


@pytest.mark.parametrize(
    "key",
    ["", "/abs", "../etc/passwd", "a/../b", "a/./b", "a//b", "a\\b", ".hidden", "a b", "x" * 513],
)
def test_invalid_keys_rejected(key: str) -> None:
    with pytest.raises(InvalidKeyError):
        validate_key(key)


# -- local backend --------------------------------------------------------------


async def test_local_put_get_exists_delete(local: LocalObjectStorage, tmp_path: Path) -> None:
    stored = await local.put("uploads/u/a/f.bin", b"\x00\x01binary", content_type="image/png")
    assert stored.size_bytes == 8
    assert await local.exists("uploads/u/a/f.bin")
    assert (tmp_path / "store" / "uploads" / "u" / "a" / "f.bin").is_file()

    data, content_type = await local.get("uploads/u/a/f.bin")
    assert data == b"\x00\x01binary"
    assert content_type == "image/png"

    await local.delete("uploads/u/a/f.bin")
    assert not await local.exists("uploads/u/a/f.bin")
    await local.delete("uploads/u/a/f.bin")  # idempotent
    with pytest.raises(ObjectNotFoundError):
        await local.get("uploads/u/a/f.bin")


async def test_local_rejects_traversal(local: LocalObjectStorage) -> None:
    with pytest.raises(InvalidKeyError):
        await local.put("../outside.txt", b"x", content_type="text/plain")
    with pytest.raises(InvalidKeyError):
        await local.get("a/../../outside.txt")


async def test_local_signed_url_shape_and_verification(local: LocalObjectStorage) -> None:
    url = await local.signed_url("uploads/u/a/f.bin", ttl_seconds=60, filename="photo.jpg")
    parsed = urlparse(url)
    assert parsed.scheme == "http" and parsed.netloc == "api.test"
    assert parsed.path == "/api/v1/files/uploads/u/a/f.bin"
    q = parse_qs(parsed.query)
    assert q["filename"] == ["photo.jpg"]
    exp, sig = int(q["exp"][0]), q["sig"][0]
    assert local.verify_signature("uploads/u/a/f.bin", expires=exp, signature=sig)
    assert not local.verify_signature("uploads/u/a/other", expires=exp, signature=sig)
    assert not local.verify_signature("uploads/u/a/f.bin", expires=exp + 1, signature=sig)
    assert not local.verify_signature("uploads/u/a/f.bin", expires=exp, signature="0" * 64)


async def test_local_signature_expires(local: LocalObjectStorage) -> None:
    url = await local.signed_url("k/f", ttl_seconds=10)
    q = parse_qs(urlparse(url).query)
    past = int(time.time()) - 1
    # Same secret, but an expiry in the past is refused even if signed correctly.
    from app.providers.storage.local import _sign

    assert not local.verify_signature("k/f", expires=past, signature=_sign(SECRET, "k/f", past))
    assert local.verify_signature("k/f", expires=int(q["exp"][0]), signature=q["sig"][0])


# -- download route (local backend) ---------------------------------------------


async def test_download_route_serves_signed_object(client: AsyncClient) -> None:
    storage = client._transport.app.state.storage  # type: ignore[attr-defined]
    await storage.put("uploads/u/a/f.txt", b"hello", content_type="text/plain")
    url = await storage.signed_url("uploads/u/a/f.txt", ttl_seconds=60, filename="f.txt")
    path_and_query = url.split("/api/v1", 1)[1]

    r = await client.get(path_and_query)
    assert r.status_code == 200
    assert r.content == b"hello"
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["cache-control"] == "private, no-store"
    assert r.headers["content-disposition"] == 'attachment; filename="f.txt"'


async def test_download_route_rejects_bad_or_expired_signature(client: AsyncClient) -> None:
    storage = client._transport.app.state.storage  # type: ignore[attr-defined]
    await storage.put("uploads/u/a/f.txt", b"hello", content_type="text/plain")
    url = await storage.signed_url("uploads/u/a/f.txt", ttl_seconds=60)
    q = parse_qs(urlparse(url).query)
    exp, sig = q["exp"][0], q["sig"][0]

    r = await client.get(f"/files/uploads/u/a/f.txt?exp={exp}&sig={'0' * 64}")
    assert r.status_code == 403
    assert r.json()["error"]["code"] == "LINK_INVALID"

    r = await client.get(f"/files/uploads/u/a/f.txt?exp={int(exp) - 3600}&sig={sig}")
    assert r.status_code == 403

    r = await client.get(f"/files/uploads/u/a/f.txt?exp={exp}&sig=not-hex")
    assert r.status_code == 422

    r = await client.get(f"/files/uploads/u/a/missing.txt?exp={exp}&sig={sig}")
    assert r.status_code == 403  # signature is for another key; existence never leaks


async def test_download_route_missing_object_is_404(client: AsyncClient) -> None:
    storage = client._transport.app.state.storage  # type: ignore[attr-defined]
    url = await storage.signed_url("uploads/u/a/never-written.txt", ttl_seconds=60)
    r = await client.get(url.split("/api/v1", 1)[1])
    assert r.status_code == 404


# -- S3 backend (client stubbed; no network) -------------------------------------


class _NoSuchKeyError(Exception):
    pass


class _ClientError(Exception):
    def __init__(self, code: str) -> None:
        self.response = {"Error": {"Code": code}}


class _Body:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.calls: list[tuple[str, dict[str, Any]]] = []

        class _Exc:
            NoSuchKey = _NoSuchKeyError
            ClientError = _ClientError

        self.exceptions = _Exc()

    def put_object(self, **kw: Any) -> None:
        self.calls.append(("put_object", kw))
        self.objects[kw["Key"]] = (kw["Body"], kw["ContentType"])

    def get_object(self, **kw: Any) -> dict[str, Any]:
        if kw["Key"] not in self.objects:
            raise _NoSuchKeyError
        body, ct = self.objects[kw["Key"]]
        return {"Body": _Body(body), "ContentType": ct}

    def head_object(self, **kw: Any) -> None:
        if kw["Key"] not in self.objects:
            raise _ClientError("404")

    def delete_object(self, **kw: Any) -> None:
        self.objects.pop(kw["Key"], None)

    def generate_presigned_url(self, op: str, **kw: Any) -> str:
        self.calls.append(("presign", {"op": op, **kw}))
        return f"https://bucket.example/{kw['Params']['Key']}?X-Amz-Expires={kw['ExpiresIn']}"


async def test_s3_adapter_round_trip() -> None:
    fake = FakeS3Client()
    s3 = S3ObjectStorage(fake, "verixa-private")  # type: ignore[arg-type]

    await s3.put("uploads/u/a/f.png", b"png", content_type="image/png")
    assert fake.calls[0] == (
        "put_object",
        {
            "Bucket": "verixa-private",
            "Key": "uploads/u/a/f.png",
            "Body": b"png",
            "ContentType": "image/png",
        },
    )
    assert await s3.exists("uploads/u/a/f.png")
    assert await s3.get("uploads/u/a/f.png") == (b"png", "image/png")

    url = await s3.signed_url("uploads/u/a/f.png", ttl_seconds=120, filename="x.png")
    assert url.startswith("https://bucket.example/uploads/u/a/f.png")
    presign = fake.calls[-1][1]
    assert presign["ExpiresIn"] == 120
    assert presign["Params"]["ResponseContentDisposition"] == 'attachment; filename="x.png"'

    await s3.delete("uploads/u/a/f.png")
    assert not await s3.exists("uploads/u/a/f.png")
    with pytest.raises(ObjectNotFoundError):
        await s3.get("uploads/u/a/f.png")


async def test_s3_adapter_validates_keys() -> None:
    s3 = S3ObjectStorage(FakeS3Client(), "b")  # type: ignore[arg-type]
    with pytest.raises(InvalidKeyError):
        await s3.put("../x", b"", content_type="text/plain")


# -- key layout -----------------------------------------------------------------


def test_storage_key_layout() -> None:
    import uuid

    u, a, r = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    up = storage_keys.upload_key(u, a, "ab" * 32, ".JPG")
    assert up == f"uploads/{u}/{a}/{'ab' * 32}.jpg"
    assert validate_key(up)
    assert validate_key(storage_keys.artifact_key(u, a, "ela.png"))
    assert validate_key(storage_keys.report_key(u, a, r, "PDF")).endswith(".pdf")
    assert all(
        p.startswith(("uploads/", "artifacts/", "reports/"))
        for p in storage_keys.analysis_prefix(u, a)
    )
