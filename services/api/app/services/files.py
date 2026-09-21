"""Serves local-storage objects through signed, short-lived links.

Only used when the storage backend is ``local``; S3 presigned URLs bypass the API.
"""

from app.providers.storage.base import InvalidKeyError, ObjectNotFoundError, ObjectStorage
from app.providers.storage.local import LocalObjectStorage
from app.utils.errors import ForbiddenError, NotFoundError

LINK_INVALID = "This download link is invalid or has expired."


async def read_signed_object(
    storage: ObjectStorage, *, key: str, expires: int, signature: str
) -> tuple[bytes, str]:
    if not isinstance(storage, LocalObjectStorage):
        raise NotFoundError("Not found.")
    try:
        if not storage.verify_signature(key, expires=expires, signature=signature):
            raise ForbiddenError(LINK_INVALID, code="LINK_INVALID")
        return await storage.get(key)
    except (InvalidKeyError, ObjectNotFoundError) as exc:
        raise NotFoundError("Not found.") from exc
