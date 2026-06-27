from __future__ import annotations

import io
import mimetypes
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from omniaudit.modules.github.auth import GitHubAuthProvider


class GitHubClientError(RuntimeError):
    """Raised on GitHub API failures."""


@dataclass(slots=True)
class GitHubClient:
    auth_provider: GitHubAuthProvider
    api_base: str = "https://api.github.com"

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type(httpx.HTTPError),
        reraise=True,
    )
    def _request(self, method: str, path: str, **kwargs) -> httpx.Response:
        headers = {
            "Authorization": self.auth_provider.authorization_header(),
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            **kwargs.pop("headers", {}),
        }
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.request(method, f"{self.api_base}{path}", headers=headers, **kwargs)
            if response.status_code >= 400:
                raise GitHubClientError(
                    f"GitHub API error {response.status_code} on {method} {path}: {response.text}"
                )
            return response

    @staticmethod
    def _split_repo(repo: str) -> tuple[str, str]:
        if "/" not in repo:
            raise ValueError("repo must be owner/name")
        owner, name = repo.split("/", 1)
        return owner, name

    def list_workflow_runs(
        self, repo: str, branch: str | None = None, per_page: int = 20
    ) -> list[dict[str, Any]]:
        owner, name = self._split_repo(repo)
        params: dict[str, Any] = {"per_page": per_page}
        if branch:
            params["branch"] = branch
        response = self._request("GET", f"/repos/{owner}/{name}/actions/runs", params=params)
        return response.json().get("workflow_runs", [])

    def list_run_artifacts(
        self, repo: str, run_id: int, per_page: int = 50
    ) -> list[dict[str, Any]]:
        owner, name = self._split_repo(repo)
        response = self._request(
            "GET",
            f"/repos/{owner}/{name}/actions/runs/{run_id}/artifacts",
            params={"per_page": per_page},
        )
        return response.json().get("artifacts", [])

    def download_artifact_zip(self, repo: str, artifact_id: int) -> bytes:
        owner, name = self._split_repo(repo)
        response = self._request(
            "GET",
            f"/repos/{owner}/{name}/actions/artifacts/{artifact_id}/zip",
            headers={"Accept": "application/vnd.github+json"},
        )
        return response.content

    def extract_text_files_from_zip(self, zip_bytes: bytes) -> dict[str, str]:
        files: dict[str, str] = {}
        with zipfile.ZipFile(io.BytesIO(zip_bytes), mode="r") as archive:
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                with archive.open(entry) as handle:
                    try:
                        files[entry.filename] = handle.read().decode("utf-8")
                    except UnicodeDecodeError:
                        continue
        return files

    def create_issue(
        self,
        repo: str,
        title: str,
        body: str,
        labels: list[str] | None = None,
        assignees: list[str] | None = None,
        milestone: int | None = None,
    ) -> dict[str, Any]:
        owner, name = self._split_repo(repo)
        payload: dict[str, Any] = {
            "title": title,
            "body": body,
            "labels": labels or [],
        }
        if assignees:
            payload["assignees"] = assignees
        if milestone is not None:
            payload["milestone"] = milestone
        response = self._request(
            "POST",
            f"/repos/{owner}/{name}/issues",
            json=payload,
        )
        return response.json()

    def get_latest_release(self, repo: str) -> dict[str, Any]:
        owner, name = self._split_repo(repo)
        response = self._request("GET", f"/repos/{owner}/{name}/releases/latest")
        return response.json()

    def get_release_by_tag(self, repo: str, tag: str) -> dict[str, Any]:
        owner, name = self._split_repo(repo)
        response = self._request("GET", f"/repos/{owner}/{name}/releases/tags/{tag}")
        return response.json()

    def list_commits(self, repo: str, per_page: int = 20) -> list[dict[str, Any]]:
        owner, name = self._split_repo(repo)
        response = self._request(
            "GET", f"/repos/{owner}/{name}/commits", params={"per_page": per_page}
        )
        return response.json()

    def list_releases(self, repo: str, per_page: int = 30) -> list[dict[str, Any]]:
        owner, name = self._split_repo(repo)
        response = self._request(
            "GET", f"/repos/{owner}/{name}/releases", params={"per_page": per_page}
        )
        return response.json()

    def compare_commits(self, repo: str, base: str, head: str) -> dict[str, Any]:
        owner, name = self._split_repo(repo)
        response = self._request("GET", f"/repos/{owner}/{name}/compare/{base}...{head}")
        return response.json()

    def download_release_asset(self, repo: str, asset_id: int) -> bytes:
        owner, name = self._split_repo(repo)
        response = self._request(
            "GET",
            f"/repos/{owner}/{name}/releases/assets/{asset_id}",
            headers={"Accept": "application/octet-stream"},
        )
        return response.content

    def create_release(
        self,
        repo: str,
        tag: str,
        notes: str,
        name: str | None = None,
        draft: bool = False,
        prerelease: bool = False,
    ) -> dict[str, Any]:
        owner, repository = self._split_repo(repo)
        response = self._request(
            "POST",
            f"/repos/{owner}/{repository}/releases",
            json={
                "tag_name": tag,
                "name": name or tag,
                "body": notes,
                "draft": draft,
                "prerelease": prerelease,
            },
        )
        return response.json()

    def upload_release_asset(
        self,
        upload_url: str,
        file_path: str,
        asset_name: str | None = None,
        content_type: str | None = None,
    ) -> dict[str, Any]:
        path = Path(file_path)
        name = asset_name or path.name
        mime_type = content_type or mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        endpoint = upload_url.split("{", 1)[0]
        params = {"name": name}

        with path.open("rb") as handle:
            content = handle.read()

        headers = {
            "Authorization": self.auth_provider.authorization_header(),
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "Content-Type": mime_type,
        }

        with httpx.Client(timeout=60.0, follow_redirects=True) as client:
            response = client.post(endpoint, headers=headers, params=params, content=content)
            if response.status_code >= 400:
                raise GitHubClientError(
                    f"GitHub asset upload error {response.status_code}: {response.text}"
                )
            return response.json()
