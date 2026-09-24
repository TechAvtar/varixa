"""S3-compatible object storage (AWS S3, Cloudflare R2, MinIO, ...).

The bucket must be private; reads happen only through presigned URLs.
boto3 is synchronous, so every call runs in a worker thread.
"""

import asyncio
from typing import TYPE_CHECKING

from app.providers.storage.base import ObjectNotFoundError, StoredObject, validate_key

if TYPE_CHECKING:
    from mypy_boto3_s3 import S3Client


class S3ObjectStorage:
    def __init__(self, client: "S3Client", bucket: str) -> None:
        self._client = client
        self._bucket = bucket

    @classmethod
    def from_credentials(
        cls,
        *,
        bucket: str,
        endpoint_url: str | None,
        region: str,
        access_key_id: str,
        secret_access_key: str,
    ) -> "S3ObjectStorage":
        import boto3
        from botocore.config import Config

        client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )
        return cls(client, bucket)

    async def put(self, key: str, data: bytes, *, content_type: str) -> StoredObject:
        validate_key(key)
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self._bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
        )
        return StoredObject(key=key, size_bytes=len(data), content_type=content_type)

    async def get(self, key: str) -> tuple[bytes, str]:
        validate_key(key)
        try:
            response = await asyncio.to_thread(
                lambda: self._client.get_object(Bucket=self._bucket, Key=key)
            )
        except self._client.exceptions.NoSuchKey as exc:
            raise ObjectNotFoundError(key) from exc
        body: bytes = await asyncio.to_thread(response["Body"].read)
        return body, response.get("ContentType") or "application/octet-stream"

    async def exists(self, key: str) -> bool:
        validate_key(key)
        try:
            await asyncio.to_thread(self._client.head_object, Bucket=self._bucket, Key=key)
        except self._client.exceptions.ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in {"404", "NoSuchKey", "NotFound"}:
                return False
            raise
        return True

    async def probe(self) -> bool:
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
        except Exception:  # readiness only; the reason stays out of responses
            return False
        return True

    async def delete(self, key: str) -> None:
        validate_key(key)
        await asyncio.to_thread(self._client.delete_object, Bucket=self._bucket, Key=key)

    async def signed_url(self, key: str, *, ttl_seconds: int, filename: str | None = None) -> str:
        validate_key(key)
        params: dict[str, str] = {"Bucket": self._bucket, "Key": key}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
        url: str = await asyncio.to_thread(
            self._client.generate_presigned_url,
            "get_object",
            Params=params,
            ExpiresIn=ttl_seconds,
        )
        return url
