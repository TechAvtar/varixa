"""Filesystem-backed object storage for local development.

Objects live under ``root/<key>`` with a ``<key>.meta.json`` sidecar for the
content type. Signed URLs are HMAC tokens verified by the API's file route.
"""

import asyncio
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from urllib.parse import quote, urlencode

from app.providers.storage.base import (
    ObjectNotFoundError,
    StoredObject,
    validate_key,
)

_META_SUFFIX = ".meta.json"
DOWNLOAD_PATH = "/api/v1/files"


def _sign(secret: str, key: str, expires: int) -> str:
    msg = f"{key}\n{expires}".encode()
    return hmac.new(secret.encode(), msg, hashlib.sha256).hexdigest()


class LocalObjectStorage:
    def __init__(self, *, root: Path, secret: str, public_base_url: str) -> None:
        self._root = root.resolve()
        self._secret = secret
        self._base = public_base_url.rstrip("/")

    # -- path safety ------------------------------------------------------------

    def _path(self, key: str) -> Path:
        validate_key(key)
        path = (self._root / key).resolve()
        if self._root not in path.parents:
            raise ObjectNotFoundError(key)  # defence in depth; validate_key already forbids this
        return path

    # -- interface --------------------------------------------------------------

    async def put(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        path = self._path(key)

        def _write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            meta = {"content_type": content_type, "size_bytes": len(data)}
            path.with_name(path.name + _META_SUFFIX).write_text(json.dumps(meta), encoding="utf-8")

        await asyncio.to_thread(_write)
        return StoredObject(key=key, size_bytes=len(data), content_type=content_type)

    async def get(self, key: str) -> tuple[bytes, str]:
        path = self._path(key)

        def _read() -> tuple[bytes, str]:
            if not path.is_file():
                raise ObjectNotFoundError(key)
            meta_path = path.with_name(path.name + _META_SUFFIX)
            content_type = "application/octet-stream"
            if meta_path.is_file():
                content_type = json.loads(meta_path.read_text(encoding="utf-8")).get(
                    "content_type", content_type
                )
            return path.read_bytes(), content_type

        return await asyncio.to_thread(_read)

    async def exists(self, key: str) -> bool:
        path = self._path(key)
        return await asyncio.to_thread(path.is_file)

    async def probe(self) -> bool:
        def _check() -> bool:
            return self._root.is_dir() and os.access(self._root, os.W_OK)

        return await asyncio.to_thread(_check)

    async def delete(self, key: str) -> None:
        path = self._path(key)

        def _delete() -> None:
            path.unlink(missing_ok=True)
            path.with_name(path.name + _META_SUFFIX).unlink(missing_ok=True)

        await asyncio.to_thread(_delete)

    async def signed_url(self, key: str, *, ttl_seconds: int, filename: str | None = None) -> str:
        validate_key(key)
        expires = int(time.time()) + ttl_seconds
        params = {"exp": str(expires), "sig": _sign(self._secret, key, expires)}
        if filename:
            params["filename"] = filename
        return f"{self._base}{DOWNLOAD_PATH}/{quote(key, safe='/')}?{urlencode(params)}"

    # -- used by the download route ---------------------------------------------

    def verify_signature(self, key: str, *, expires: int, signature: str) -> bool:
        if expires < int(time.time()):
            return False
        return hmac.compare_digest(_sign(self._secret, key, expires), signature)
