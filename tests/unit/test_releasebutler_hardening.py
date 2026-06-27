from __future__ import annotations

from pathlib import Path

from omniaudit.modules.releasebutler.service import ReleaseButlerService


class FakeGitHub:
    def __init__(self, compare_fails: bool = False) -> None:
        self.compare_fails = compare_fails
        self.uploaded: list[dict] = []

    def get_latest_release(self, repo: str) -> dict:
        return {
            "id": 2,
            "tag_name": "v2.0.0",
            "name": "v2.0.0",
            "html_url": "https://example/release/v2",
            "upload_url": "https://uploads.example/releases/2/assets{?name,label}",
            "assets": [],
        }

    def list_releases(self, repo: str, per_page: int = 30) -> list[dict]:
        return [
            {"tag_name": "v2.0.0"},
            {"tag_name": "v1.0.0"},
        ]

    def compare_commits(self, repo: str, base: str, head: str) -> dict:
        if self.compare_fails:
            raise RuntimeError("compare failed")
        return {
            "commits": [
                {"sha": "a" * 40, "commit": {"message": "feat: add release flow"}},
                {"sha": "b" * 40, "commit": {"message": "fix: retry logic"}},
                {"sha": "c" * 40, "commit": {"message": "docs: update runbook"}},
            ]
        }

    def list_commits(self, repo: str, per_page: int = 20) -> list[dict]:
        return [
            {"sha": "d" * 40, "commit": {"message": "chore: fallback commit path"}},
        ]

    def create_release(
        self,
        repo: str,
        tag: str,
        notes: str,
        name: str | None = None,
        draft: bool = False,
        prerelease: bool = False,
    ) -> dict:
        return {
            "id": 3,
            "html_url": "https://example/release/v3",
            "upload_url": "https://uploads.example/releases/3/assets{?name,label}",
        }

    def upload_release_asset(
        self,
        upload_url: str,
        file_path: str,
        asset_name: str,
        content_type: str,
    ) -> dict:
        self.uploaded.append(
            {"upload_url": upload_url, "file_path": file_path, "asset_name": asset_name}
        )
        return {
            "id": 99,
            "name": asset_name,
            "size": Path(file_path).stat().st_size,
            "browser_download_url": f"https://example/download/{asset_name}",
        }


def test_generate_notes_uses_tag_compare_by_default() -> None:
    svc = ReleaseButlerService(github=FakeGitHub())

    result = svc.generate_notes(repo="o/r", tag=None, window=20)

    assert result["range"]["from_tag"] == "v1.0.0"
    assert result["range"]["to_tag"] == "v2.0.0"
    assert result["range"]["fallback_used"] is False
    assert result["range"]["commit_count"] == 3
    assert "## Summary" in result["notes"]
    assert "feat: add release flow" in result["notes"]


def test_generate_notes_falls_back_when_compare_fails() -> None:
    svc = ReleaseButlerService(github=FakeGitHub(compare_fails=True))

    result = svc.generate_notes(repo="o/r", tag=None, window=20)

    assert result["range"]["fallback_used"] is True
    assert result["range"]["commit_count"] == 1
    assert "fallback commit path" in result["notes"]


def test_create_release_uploads_local_assets_and_reports_failures(tmp_path: Path) -> None:
    svc = ReleaseButlerService(github=FakeGitHub())

    valid_file = tmp_path / "artifact.zip"
    valid_file.write_bytes(b"zip-content")
    missing_file = tmp_path / "missing.zip"

    result = svc.create_release(
        repo="o/r",
        tag="v3.0.0",
        notes="release notes",
        assets=[str(valid_file), str(missing_file)],
    )

    assert result["release_id"] == 3
    assert len(result["uploaded_assets"]) == 1
    assert result["uploaded_assets"][0]["name"] == "artifact.zip"
    assert len(result["failed_assets"]) == 1
    assert result["failed_assets"][0]["path"] == str(missing_file)
