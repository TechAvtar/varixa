"""Private object storage behind one interface: local filesystem or S3-compatible."""

from app.config import Settings
from app.providers.storage.base import ObjectStorage, StoredObject
from app.providers.storage.local import LocalObjectStorage


def build_storage(settings: Settings) -> ObjectStorage:
    if settings.storage_backend == "local":
        assert settings.storage_local_path is not None  # guaranteed by Settings validator
        return LocalObjectStorage(
            root=settings.storage_local_path,
            secret=settings.secret_key.get_secret_value(),
            public_base_url=settings.api_public_url,
        )
    from app.providers.storage.s3 import S3ObjectStorage  # optional dependency

    assert settings.s3_bucket and settings.s3_access_key_id and settings.s3_secret_access_key
    return S3ObjectStorage.from_credentials(
        bucket=settings.s3_bucket,
        endpoint_url=settings.s3_endpoint_url,
        region=settings.s3_region,
        access_key_id=settings.s3_access_key_id.get_secret_value(),
        secret_access_key=settings.s3_secret_access_key.get_secret_value(),
    )


__all__ = ["LocalObjectStorage", "ObjectStorage", "StoredObject", "build_storage"]
