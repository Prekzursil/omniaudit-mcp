from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from omniaudit.modules.github import auth as auth_module
from omniaudit.modules.github import client as client_module
from omniaudit.modules.github.auth import (
    GitHubAppAuthProvider,
    PATAuthProvider,
)
from omniaudit.modules.github.client import GitHubClient, GitHubClientError

_REAL_CLIENT = httpx.Client


def _install_mock(monkeypatch, handler) -> None:
    def make_client(*args, **kwargs):
        return _REAL_CLIENT(transport=httpx.MockTransport(handler), follow_redirects=True)

    monkeypatch.setattr(client_module.httpx, "Client", make_client)


@pytest.fixture
def client() -> GitHubClient:
    return GitHubClient(auth_provider=PATAuthProvider("tok"))


def test_pat_auth_header() -> None:
    assert PATAuthProvider("abc").authorization_header() == "Bearer abc"


def test_split_repo_validation(client: GitHubClient) -> None:
    with pytest.raises(ValueError, match="owner/name"):
        client.list_workflow_runs("invalid-repo")


def test_request_raises_on_error_status(client: GitHubClient, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    _install_mock(monkeypatch, handler)
    with pytest.raises(GitHubClientError, match="GitHub API error 404"):
        client.get_latest_release("o/r")


def test_read_only_endpoints(client: GitHubClient, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/actions/runs"):
            assert request.url.params.get("branch") == "main"
            return httpx.Response(200, json={"workflow_runs": [{"id": 1}]})
        if path.endswith("/artifacts"):
            return httpx.Response(200, json={"artifacts": [{"id": 7, "name": "a"}]})
        if path.endswith("/zip"):
            return httpx.Response(200, content=b"zipbytes")
        if path.endswith("/releases/latest"):
            return httpx.Response(200, json={"tag_name": "v1"})
        if "/releases/tags/" in path:
            return httpx.Response(200, json={"tag_name": "v1"})
        if path.endswith("/commits"):
            return httpx.Response(200, json=[{"sha": "abc"}])
        if path.endswith("/releases"):
            return httpx.Response(200, json=[{"tag_name": "v1"}])
        if "/compare/" in path:
            return httpx.Response(200, json={"commits": []})
        if "/releases/assets/" in path:
            return httpx.Response(200, content=b"asset")
        return httpx.Response(200, json={})  # pragma: no cover - defensive default

    _install_mock(monkeypatch, handler)
    assert client.list_workflow_runs("o/r", branch="main") == [{"id": 1}]
    assert client.list_run_artifacts("o/r", 1) == [{"id": 7, "name": "a"}]
    assert client.download_artifact_zip("o/r", 7) == b"zipbytes"
    assert client.get_latest_release("o/r")["tag_name"] == "v1"
    assert client.get_release_by_tag("o/r", "v1")["tag_name"] == "v1"
    assert client.list_commits("o/r") == [{"sha": "abc"}]
    assert client.list_releases("o/r") == [{"tag_name": "v1"}]
    assert client.compare_commits("o/r", "a", "b") == {"commits": []}
    assert client.download_release_asset("o/r", 5) == b"asset"


def test_list_workflow_runs_without_branch_and_minimal_issue(
    client: GitHubClient, monkeypatch
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/actions/runs"):
            assert "branch" not in request.url.params
            return httpx.Response(200, json={"workflow_runs": []})
        return httpx.Response(201, json={"number": 1})

    _install_mock(monkeypatch, handler)
    assert client.list_workflow_runs("o/r") == []
    # No assignees and no milestone exercise the falsy branches.
    assert client.create_issue("o/r", "t", "b")["number"] == 1


def test_write_endpoints(client: GitHubClient, monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/issues"):
            return httpx.Response(201, json={"html_url": "u", "number": 3})
        if request.url.path.endswith("/releases"):
            return httpx.Response(201, json={"id": 9, "html_url": "ru"})
        return httpx.Response(200, json={})  # pragma: no cover - defensive default

    _install_mock(monkeypatch, handler)
    issue = client.create_issue("o/r", "t", "b", labels=["x"], assignees=["me"], milestone=2)
    assert issue["number"] == 3
    release = client.create_release("o/r", "v2", "notes", draft=True, prerelease=True)
    assert release["id"] == 9


def test_extract_text_files_from_zip(client: GitHubClient) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("dir/", "")  # directory entry -> skipped
        archive.writestr("ok.txt", "hello")
        archive.writestr("bin.dat", b"\xff\xfe\x00binary")
    files = client.extract_text_files_from_zip(buffer.getvalue())
    assert files == {"ok.txt": "hello"}


def test_upload_release_asset(client: GitHubClient, monkeypatch, tmp_path: Path) -> None:
    asset = tmp_path / "artifact.bin"
    asset.write_bytes(b"payload")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("name") == "artifact.bin"
        return httpx.Response(201, json={"id": 1, "name": "artifact.bin"})

    _install_mock(monkeypatch, handler)
    result = client.upload_release_asset(
        "https://uploads.github.com/repos/o/r/releases/9/assets{?name,label}",
        str(asset),
    )
    assert result["name"] == "artifact.bin"


def test_upload_release_asset_error(client: GitHubClient, monkeypatch, tmp_path: Path) -> None:
    asset = tmp_path / "a.bin"
    asset.write_bytes(b"x")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    _install_mock(monkeypatch, handler)
    with pytest.raises(GitHubClientError, match="asset upload error 500"):
        client.upload_release_asset(
            "https://uploads.example/x", str(asset), content_type="text/plain"
        )


# ---------------- GitHubAppAuthProvider ----------------
def _rsa_pem() -> str:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")


def test_app_auth_fetches_and_caches_token(monkeypatch) -> None:
    # Far-future expiry so the cache stays valid regardless of local timezone offset.
    expires = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time() + 86400))
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(201, json={"token": "ghs_token", "expires_at": expires})

    def make_client(*args, **kwargs):
        return _REAL_CLIENT(transport=httpx.MockTransport(handler))

    monkeypatch.setattr(auth_module.httpx, "Client", make_client)

    provider = GitHubAppAuthProvider(app_id="1", installation_id="2", private_key_pem=_rsa_pem())
    assert provider.authorization_header() == "Bearer ghs_token"
    # Second call uses the cached token (no extra HTTP request).
    assert provider.authorization_header() == "Bearer ghs_token"
    assert calls["n"] == 1


def test_app_auth_jwt_bytes_branch(monkeypatch) -> None:
    monkeypatch.setattr(auth_module.jwt, "encode", lambda *a, **k: b"jwt-bytes")
    provider = GitHubAppAuthProvider(app_id="1", installation_id="2", private_key_pem="pem")
    assert provider._create_app_jwt() == "jwt-bytes"
