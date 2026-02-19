from __future__ import annotations

import io
import json
from pathlib import Path

from omniaudit.storage.dual import DualReadObjectStore
from omniaudit.storage.objects import LocalObjectStore
from omniaudit.storage.s3 import S3ObjectStore


class FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes, ContentType: str) -> dict:
        self.objects[(Bucket, Key)] = Body
        return {"ETag": "fake"}

    def get_object(self, *, Bucket: str, Key: str) -> dict:
        body = self.objects[(Bucket, Key)]
        return {"Body": io.BytesIO(body)}


def test_s3_object_store_writes_and_reads_immutable() -> None:
    fake = FakeS3Client()
    store = S3ObjectStore(bucket="omia", prefix="omniaudit", client=fake)

    ref_1 = store.put_json_immutable({"hello": "world"})
    ref_2 = store.put_json_immutable({"hello": "world"})

    assert ref_1 == ref_2
    assert ref_1.startswith("s3://omia/omniaudit/")
    payload = json.loads(store.read_text(ref_1))
    assert payload == {"hello": "world"}


def test_dual_read_object_store_reads_legacy_local_and_new_s3(tmp_path: Path) -> None:
    local = LocalObjectStore(tmp_path / "local")
    legacy_ref = local.put_json_immutable({"legacy": True})

    fake = FakeS3Client()
    s3_store = S3ObjectStore(bucket="omia", prefix="omniaudit", client=fake)
    dual = DualReadObjectStore(primary=s3_store, fallback=local)

    assert json.loads(dual.read_text(legacy_ref)) == {"legacy": True}

    new_ref = dual.put_json_immutable({"new": True})
    assert new_ref.startswith("s3://omia/omniaudit/")
    assert json.loads(dual.read_text(new_ref)) == {"new": True}
