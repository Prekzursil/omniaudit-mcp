from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

import boto3

from omniaudit.storage.base import ObjectStore


@dataclass(slots=True)
class S3ObjectStore(ObjectStore):
    bucket: str
    prefix: str = "omniaudit"
    endpoint_url: str | None = None
    region_name: str | None = None
    force_path_style: bool = True
    access_key_id: str | None = None
    secret_access_key: str | None = None
    client: Any | None = None

    def __post_init__(self) -> None:
        if self.client is None:
            config = None
            if self.force_path_style:
                from botocore.config import Config

                config = Config(s3={"addressing_style": "path"})
            self.client = boto3.client(
                "s3",
                endpoint_url=self.endpoint_url,
                region_name=self.region_name,
                aws_access_key_id=self.access_key_id,
                aws_secret_access_key=self.secret_access_key,
                config=config,
            )

    def put_json_immutable(self, document: dict) -> str:
        body = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
        digest = hashlib.sha256(body).hexdigest()
        key = self._key(f"{digest}.json")
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=body,
            ContentType="application/json",
        )
        return f"s3://{self.bucket}/{key}"

    def put_bytes_immutable(self, content: bytes, suffix: str = ".bin") -> str:
        digest = hashlib.sha256(content).hexdigest()
        key = self._key(f"{digest}{suffix}")
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=content,
            ContentType="application/octet-stream",
        )
        return f"s3://{self.bucket}/{key}"

    def read_text(self, ref: str) -> str:
        return self.read_bytes(ref).decode("utf-8")

    def read_bytes(self, ref: str) -> bytes:
        bucket, key = self._parse_ref(ref)
        obj = self.client.get_object(Bucket=bucket, Key=key)
        body = obj["Body"].read()
        if isinstance(body, str):
            return body.encode("utf-8")
        return body

    def _key(self, leaf: str) -> str:
        prefix = self.prefix.strip("/")
        return f"{prefix}/{leaf}" if prefix else leaf

    @staticmethod
    def _parse_ref(ref: str) -> tuple[str, str]:
        parsed = urlparse(ref)
        if parsed.scheme != "s3":
            raise ValueError(f"Unsupported S3 ref: {ref}")
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        return bucket, key
