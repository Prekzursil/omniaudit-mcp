from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from omniaudit.storage.engine import (
    create_db_engine,
    create_session_factory,
    initialize_database,
)


@pytest.fixture
def session_factory(tmp_path: Path):
    db_path = tmp_path / "test.db"
    engine = create_db_engine(f"sqlite+pysqlite:///{db_path.as_posix()}")
    initialize_database(engine)
    return create_session_factory(engine)


@pytest.fixture
def local_store(tmp_path: Path):
    from omniaudit.storage.objects import LocalObjectStore

    return LocalObjectStore(tmp_path / "objects")


class FakeGitHub:
    """In-memory stand-in for GitHubClient used to exercise service logic."""

    def __init__(self, **responses: Any) -> None:
        self.responses = responses
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def _record(self, _call: str, *args: Any, **kwargs: Any) -> Any:
        self.calls.append((_call, args, kwargs))
        value = self.responses.get(_call)
        if isinstance(value, Exception):
            raise value
        return value

    def list_workflow_runs(self, repo, branch=None, per_page=20):
        return self._record("list_workflow_runs", repo, branch=branch) or []

    def list_run_artifacts(self, repo, run_id, per_page=50):
        return self._record("list_run_artifacts", repo, run_id) or []

    def download_artifact_zip(self, repo, artifact_id):
        return self._record("download_artifact_zip", repo, artifact_id) or b""

    def extract_text_files_from_zip(self, zip_bytes):
        return self._record("extract_text_files_from_zip", zip_bytes) or {}

    def create_issue(self, repo, title, body, labels=None, assignees=None, milestone=None):
        return (
            self._record(
                "create_issue",
                repo,
                title,
                body,
                labels=labels,
                assignees=assignees,
                milestone=milestone,
            )
            or {}
        )

    def get_latest_release(self, repo):
        return self._record("get_latest_release", repo) or {}

    def get_release_by_tag(self, repo, tag):
        return self._record("get_release_by_tag", repo, tag) or {}

    def list_commits(self, repo, per_page=20):
        return self._record("list_commits", repo, per_page=per_page) or []

    def list_releases(self, repo, per_page=30):
        return self._record("list_releases", repo, per_page=per_page) or []

    def compare_commits(self, repo, base, head):
        return self._record("compare_commits", repo, base, head) or {}

    def download_release_asset(self, repo, asset_id):
        return self._record("download_release_asset", repo, asset_id) or b""

    def create_release(self, repo, tag, notes, name=None, draft=False, prerelease=False):
        return self._record("create_release", repo, tag, notes, name=name) or {}

    def upload_release_asset(self, upload_url, file_path, asset_name=None, content_type=None):
        return (
            self._record("upload_release_asset", upload_url, file_path, asset_name=asset_name) or {}
        )


@pytest.fixture
def fake_github_factory():
    return FakeGitHub
