from __future__ import annotations

import json
from pathlib import Path

import pytest
from omniaudit.security.envelope import EnvelopeEncryption
from omniaudit.storage import s3 as s3_module
from omniaudit.storage.audit_log import AuditLogger
from omniaudit.storage.credentials import SecretCredentialStore
from omniaudit.storage.dual import DualReadObjectStore
from omniaudit.storage.jobs import JobStore, default_idempotency_key
from omniaudit.storage.objects import LocalObjectStore
from omniaudit.storage.receipts import ReceiptStore
from omniaudit.storage.s3 import S3ObjectStore


class _FakeBody:
    def __init__(self, payload: bytes | str) -> None:
        self._payload = payload

    def read(self) -> bytes | str:
        return self._payload


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}

    def put_object(self, Bucket, Key, Body, ContentType):  # noqa: N803 - boto3 kwargs
        self.objects[(Bucket, Key)] = Body

    def get_object(self, Bucket, Key):  # noqa: N803 - boto3 kwargs
        return {"Body": _FakeBody(self.objects[(Bucket, Key)])}


# ---------------- LocalObjectStore ----------------
def test_local_object_store_roundtrip_and_dedupe(tmp_path: Path) -> None:
    store = LocalObjectStore(tmp_path / "objs")
    ref = store.put_json_immutable({"b": 2, "a": 1})
    # Writing the same content again hits the "already exists" branch.
    ref_again = store.put_json_immutable({"a": 1, "b": 2})
    assert ref == ref_again
    assert store.read_text(ref) == '{"a":1,"b":2}'
    blob_ref = store.put_bytes_immutable(b"hello", suffix=".bin")
    store.put_bytes_immutable(b"hello", suffix=".bin")
    assert store.read_bytes(blob_ref) == b"hello"


# ---------------- S3ObjectStore ----------------
def test_s3_object_store_builds_client_with_path_style(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_client(service, **kwargs):
        captured["service"] = service
        captured["config"] = kwargs.get("config")
        return _FakeS3Client()

    monkeypatch.setattr(s3_module.boto3, "client", fake_client)
    store = S3ObjectStore(bucket="bk", prefix="omniaudit", force_path_style=True)
    assert captured["service"] == "s3"
    assert captured["config"] is not None

    ref = store.put_json_immutable({"a": 1})
    assert ref.startswith("s3://bk/omniaudit/")
    assert store.read_text(ref) == '{"a":1}'

    blob_ref = store.put_bytes_immutable(b"x")
    assert store.read_bytes(blob_ref) == b"x"


def test_s3_object_store_injected_client_no_path_style() -> None:
    client = _FakeS3Client()
    store = S3ObjectStore(bucket="bk", prefix="", force_path_style=False, client=client)
    ref = store.put_json_immutable({"k": "v"})
    # Empty prefix -> key has no prefix segment.
    assert ref == f"s3://bk/{ref.split('/')[-1]}"


def test_s3_read_bytes_handles_str_body() -> None:
    client = _FakeS3Client()
    store = S3ObjectStore(bucket="bk", client=client)
    client.objects[("bk", "omniaudit/file.txt")] = "plain-text"
    assert store.read_bytes("s3://bk/omniaudit/file.txt") == b"plain-text"


def test_s3_parse_ref_rejects_non_s3_scheme() -> None:
    store = S3ObjectStore(bucket="bk", client=_FakeS3Client())
    with pytest.raises(ValueError, match="Unsupported S3 ref"):
        store.read_bytes("https://example.com/x")


# ---------------- DualReadObjectStore ----------------
def test_dual_read_prefers_fallback_then_primary(tmp_path: Path) -> None:
    primary = LocalObjectStore(tmp_path / "primary")
    fallback = LocalObjectStore(tmp_path / "fallback")
    dual = DualReadObjectStore(primary=primary, fallback=fallback)

    ref = dual.put_json_immutable({"a": 1})
    blob_ref = dual.put_bytes_immutable(b"bytes")
    # Local refs come from the primary store path, so fallback read raises and we fall back to primary.
    assert json.loads(dual.read_text(ref)) == {"a": 1}
    assert dual.read_bytes(blob_ref) == b"bytes"


def test_dual_read_s3_ref_goes_to_primary() -> None:
    client = _FakeS3Client()
    primary = S3ObjectStore(bucket="bk", client=client)
    fallback = LocalObjectStore(Path("unused"))
    dual = DualReadObjectStore(primary=primary, fallback=fallback)
    ref = primary.put_json_immutable({"a": 1})
    assert dual.read_text(ref) == '{"a":1}'
    assert dual.read_bytes(ref) == b'{"a":1}'


class _RaisingStore:
    def read_text(self, ref):
        raise OSError("boom")

    def read_bytes(self, ref):
        raise OSError("boom")


def test_dual_read_falls_back_to_primary_on_fallback_error(tmp_path: Path) -> None:
    primary = LocalObjectStore(tmp_path / "pr")
    text_ref = primary.put_json_immutable({"a": 1})
    bytes_ref = primary.put_bytes_immutable(b"raw")
    dual = DualReadObjectStore(primary=primary, fallback=_RaisingStore())
    # Non-s3 ref: fallback raises -> except branch reads from primary.
    assert dual.read_text(text_ref) == '{"a":1}'
    assert dual.read_bytes(bytes_ref) == b"raw"


def test_s3_no_path_style_builds_default_config(monkeypatch) -> None:
    def fake_client(service, **kwargs):
        assert kwargs.get("config") is None
        return _FakeS3Client()

    monkeypatch.setattr(s3_module.boto3, "client", fake_client)
    store = S3ObjectStore(bucket="bk", force_path_style=False)
    assert store.put_json_immutable({"a": 1}).startswith("s3://bk/")


def test_job_status_update_without_result_ref(session_factory) -> None:
    jobs = JobStore(session_factory)
    job = jobs.create_or_get_job("sitelint", "op", "k", {})
    updated = jobs.set_job_status(job.job_id, "running", 0.5)
    assert updated.result_ref is None


def test_dual_read_fallback_hit(tmp_path: Path) -> None:
    fallback = LocalObjectStore(tmp_path / "fb")
    primary = LocalObjectStore(tmp_path / "pr")
    ref = fallback.put_json_immutable({"a": 1})
    dual = DualReadObjectStore(primary=primary, fallback=fallback)
    # ref exists in fallback (non-s3) -> served by fallback directly.
    assert dual.read_text(ref) == '{"a":1}'
    assert dual.read_bytes(ref) == b'{"a":1}'


# ---------------- JobStore ----------------
def test_job_store_lifecycle_and_idempotency(session_factory) -> None:
    jobs = JobStore(session_factory)
    job = jobs.create_or_get_job("sitelint", "op", "key-1", {"url": "x"})
    # Same idempotency key returns the existing job (early-return branch).
    again = jobs.create_or_get_job("sitelint", "op", "key-1", {"url": "x"})
    assert again.job_id == job.job_id

    assert jobs.get_job(job.job_id).job_id == job.job_id
    assert jobs.get_job("missing") is None

    updated = jobs.set_job_status(job.job_id, "completed", 1.0, result_ref="ref://1")
    assert updated.status == "completed"
    assert jobs.set_job_status("missing", "x", 0.0) is None

    jobs.create_or_get_job("releasebutler", "op2", "key-2", {})
    assert len(jobs.list_jobs()) == 2
    assert len(jobs.list_jobs(module="sitelint")) == 1


def test_default_idempotency_key_is_deterministic() -> None:
    assert default_idempotency_key("op", {"a": 1}) == default_idempotency_key("op", {"a": 1})


# ---------------- ReceiptStore ----------------
def test_receipt_store_create_and_list(session_factory, local_store) -> None:
    receipts = ReceiptStore(session_factory, local_store)
    r1 = receipts.create_receipt("op.a", "actor", {"in": 1}, {"out": 1})
    receipts.create_receipt("op.b", "actor", {"in": 2}, {"out": 2})
    assert r1.receipt_id.startswith("rcpt_")
    assert len(receipts.list_receipts()) == 2
    assert len(receipts.list_receipts(operation="op.a")) == 1


# ---------------- AuditLogger ----------------
def test_audit_logger_append(session_factory) -> None:
    logger = AuditLogger(session_factory)
    logger.append(request_id="req", tool_name="tool", inputs={"a": 1}, output_ref="ref")


# ---------------- SecretCredentialStore + EnvelopeEncryption ----------------
def test_envelope_roundtrip(tmp_path: Path) -> None:
    env = EnvelopeEncryption(tmp_path / "secrets" / "master.key")
    # Second construction reuses the existing key file (skips generation branch).
    EnvelopeEncryption(tmp_path / "secrets" / "master.key")
    token = env.encrypt_secret("super-secret")
    assert env.decrypt_secret(token) == "super-secret"


def test_secret_credential_store(session_factory, tmp_path: Path) -> None:
    from omniaudit.models.db import SecretCredential

    env = EnvelopeEncryption(tmp_path / "secrets" / "master.key")
    store = SecretCredentialStore(session_factory, env)
    assert store.get_auth_profile("missing") is None

    encrypted = env.encrypt_secret(json.dumps({"headers": {"X": "1"}}))
    with session_factory() as session:
        session.add(
            SecretCredential(credential_name="prof", provider="github", encrypted_value=encrypted)
        )
        session.commit()
    assert store.get_auth_profile("prof") == {"headers": {"X": "1"}}

    encrypted_list = env.encrypt_secret(json.dumps([1, 2, 3]))
    with session_factory() as session:
        session.add(
            SecretCredential(
                credential_name="bad", provider="github", encrypted_value=encrypted_list
            )
        )
        session.commit()
    # Non-dict payload is rejected.
    assert store.get_auth_profile("bad") is None
