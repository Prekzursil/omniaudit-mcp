from __future__ import annotations

import hashlib
from pathlib import Path

from omniaudit.modules.releasebutler.service import ReleaseButlerService


class FakeGitHubWave1:
    def __init__(self) -> None:
        self.uploaded: list[dict] = []
        self.created_release_payload: dict | None = None

    def get_latest_release(self, repo: str) -> dict:
        return {"tag_name": "v2.0.0", "assets": [], "html_url": "https://example/release/v2"}

    def list_releases(self, repo: str, per_page: int = 30) -> list[dict]:
        return [{"tag_name": "v2.0.0"}, {"tag_name": "v1.0.0"}]

    def compare_commits(self, repo: str, base: str, head: str) -> dict:
        return {
            "commits": [
                {
                    "sha": "a" * 40,
                    "commit": {"message": "feat(scanner): add crawl budget support"},
                    "author": {"login": "Prekzursil"},
                },
                {
                    "sha": "b" * 40,
                    "commit": {"message": "fix(release): handle dry_run (#42)"},
                    "author": {"login": "Prekzursil"},
                },
            ]
        }

    def list_commits(self, repo: str, per_page: int = 20) -> list[dict]:
        return []

    def create_release(
        self,
        repo: str,
        tag: str,
        notes: str,
        name: str | None = None,
        draft: bool = False,
        prerelease: bool = False,
    ) -> dict:
        self.created_release_payload = {
            "repo": repo,
            "tag": tag,
            "notes": notes,
            "name": name,
            "draft": draft,
            "prerelease": prerelease,
        }
        return {
            "id": 3,
            "html_url": "https://example/release/v3",
            "upload_url": "https://uploads.example/releases/3/assets{?name,label}",
        }

    def upload_release_asset(
        self, upload_url: str, file_path: str, asset_name: str, content_type: str | None = None
    ) -> dict:
        self.uploaded.append(
            {"upload_url": upload_url, "file_path": file_path, "asset_name": asset_name}
        )
        return {
            "id": 7,
            "name": asset_name,
            "size": Path(file_path).stat().st_size,
            "browser_download_url": f"https://example/download/{asset_name}",
        }


def test_generate_notes_supports_scope_grouping_and_pr_links() -> None:
    svc = ReleaseButlerService(github=FakeGitHubWave1())

    result = svc.generate_notes(
        repo="o/r",
        tag=None,
        from_tag="v1.0.0",
        to_tag="v2.0.0",
        group_by="scope",
        include_pr_links=True,
    )

    assert "## By Scope" in result["notes"]
    assert "(#42)" in result["notes"]
    assert result["range"]["fallback_used"] is False


def test_create_release_dry_run_validates_assets_without_publish(tmp_path: Path) -> None:
    fake = FakeGitHubWave1()
    svc = ReleaseButlerService(github=fake)
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"abc123")

    result = svc.create_release(
        repo="o/r",
        tag="v3.0.0",
        notes="notes",
        assets=[str(artifact)],
        dry_run=True,
        provenance_manifest=True,
    )

    assert result["dry_run"] is True
    assert result["release_id"] is None
    assert result["failed_assets"] == []
    assert result["uploaded_assets"] == []
    assert fake.created_release_payload is None
    assert "provenance" in result
    assert result["provenance"]["assets"][0]["sha256"] == hashlib.sha256(b"abc123").hexdigest()


def test_create_release_supports_draft_and_prerelease_flags(tmp_path: Path) -> None:
    fake = FakeGitHubWave1()
    svc = ReleaseButlerService(github=fake)
    artifact = tmp_path / "artifact.bin"
    artifact.write_bytes(b"hello")

    result = svc.create_release(
        repo="o/r",
        tag="v3.0.0",
        notes="notes",
        assets=[str(artifact)],
        draft=True,
        prerelease=True,
        provenance_manifest=True,
    )

    assert result["release_id"] == 3
    assert len(result["uploaded_assets"]) == 1
    assert fake.created_release_payload is not None
    assert fake.created_release_payload["draft"] is True
    assert fake.created_release_payload["prerelease"] is True
    assert result["provenance"]["assets"][0]["name"] == "artifact.bin"
