"""Object storage behind an interface. S3 implementation works with MinIO and AWS S3.

Keys are always prefixed with the tenant id, and files are only reachable through
short-lived signed URLs.
"""

import asyncio
import uuid
from functools import lru_cache
from typing import Any, Protocol

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from app.core.config import get_settings


class ObjectStorage(Protocol):
    async def put(self, key: str, data: bytes, content_type: str) -> None: ...
    async def get(self, key: str) -> bytes: ...
    async def signed_url(self, key: str, ttl_seconds: int | None = None) -> str: ...
    async def ensure_bucket(self) -> None: ...
    async def ping(self) -> bool: ...


def tenant_key(tenant_id: uuid.UUID, *parts: str) -> str:
    return "/".join([str(tenant_id), *parts])


class S3Storage:
    def __init__(self) -> None:
        s = get_settings()
        self.bucket = s.s3_bucket
        common: dict[str, Any] = {
            "region_name": s.s3_region,
            "aws_access_key_id": s.s3_access_key.get_secret_value(),
            "aws_secret_access_key": s.s3_secret_key.get_secret_value(),
            "config": Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        }
        self._client = boto3.client("s3", endpoint_url=s.s3_endpoint_url, **common)
        # Signed URLs must use the host the browser can reach.
        self._signer = boto3.client(
            "s3", endpoint_url=s.s3_public_endpoint_url or s.s3_endpoint_url, **common
        )
        self._ttl = s.signed_url_ttl_seconds

    async def put(self, key: str, data: bytes, content_type: str) -> None:
        await asyncio.to_thread(
            self._client.put_object,
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            ServerSideEncryption="AES256",
        )

    async def get(self, key: str) -> bytes:
        obj = await asyncio.to_thread(self._client.get_object, Bucket=self.bucket, Key=key)
        body: bytes = await asyncio.to_thread(obj["Body"].read)
        return body

    async def signed_url(self, key: str, ttl_seconds: int | None = None) -> str:
        url: str = await asyncio.to_thread(
            self._signer.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=ttl_seconds or self._ttl,
        )
        return url

    async def ensure_bucket(self) -> None:
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self.bucket)
        except ClientError:
            await asyncio.to_thread(self._client.create_bucket, Bucket=self.bucket)

    async def ping(self) -> bool:
        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self.bucket)
            return True
        except Exception:
            return False


@lru_cache
def get_storage() -> ObjectStorage:
    return S3Storage()
