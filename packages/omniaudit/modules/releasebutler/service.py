from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omniaudit.modules.github.client import GitHubClient
from omniaudit.modules.releasebutler.checksum import verify_checksum

_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(slots=True)
class ReleaseButlerService:
    github: GitHubClient

    def get_latest(self, repo: str) -> dict[str, Any]:
        release = self.github.get_latest_release(repo)
        return {
            "repo": repo,
            "tag": release.get("tag_name"),
            "name": release.get("name"),
            "published_at": release.get("published_at"),
            "assets": release.get("assets", []),
            "url": release.get("html_url"),
        }

    def list_assets(self, repo: str, tag: str | None = None) -> dict[str, Any]:
        release = self.github.get_release_by_tag(repo, tag) if tag else self.github.get_latest_release(repo)
        return {
            "repo": repo,
            "tag": release.get("tag_name"),
            "assets": [
                {
                    "id": asset.get("id"),
                    "name": asset.get("name"),
                    "size": asset.get("size"),
                    "download_count": asset.get("download_count"),
                }
                for asset in release.get("assets", [])
            ],
        }

    def verify_asset(self, repo: str, asset_id: int, checksum_source: str) -> dict[str, Any]:
        content = self.github.download_release_asset(repo, asset_id)
        expected = self._resolve_expected_checksum(repo, checksum_source)
        return {
            "repo": repo,
            "asset_id": asset_id,
            "checksum_source": checksum_source,
            "verified": verify_checksum(content, expected),
        }

    def generate_notes(
        self,
        repo: str,
        tag: str | None,
        window: int = 20,
        from_tag: str | None = None,
        to_tag: str | None = None,
        fallback_window: int | None = None,
        group_by: str | None = None,
        include_pr_links: bool = False,
    ) -> dict[str, Any]:
        releases = self.github.list_releases(repo, per_page=30)
        resolved_to = to_tag or tag or (releases[0].get("tag_name") if releases else None)
        resolved_from = from_tag or self._find_previous_tag(releases, resolved_to)

        compare_commits: list[dict[str, Any]] = []
        used_fallback = False

        if resolved_from and resolved_to:
            try:
                compare_payload = self.github.compare_commits(repo, base=resolved_from, head=resolved_to)
                compare_commits = compare_payload.get("commits", [])
            except Exception:
                used_fallback = True
        else:
            used_fallback = True

        if used_fallback:
            compare_commits = self.github.list_commits(
                repo,
                per_page=max(1, min(fallback_window or window or 20, 100)),
            )

        parsed = self._parse_commit_entries(compare_commits, repo=repo, include_pr_links=include_pr_links)
        selected_group = (group_by or "type").strip().lower()
        notes = self._build_notes_markdown(parsed, resolved_from, resolved_to, used_fallback, group_by=selected_group)

        return {
            "repo": repo,
            "tag": tag,
            "window": window,
            "notes": notes,
            "range": {
                "from_tag": resolved_from,
                "to_tag": resolved_to,
                "commit_count": len(parsed),
                "fallback_used": used_fallback,
            },
            "group_by": selected_group,
            "include_pr_links": include_pr_links,
        }

    def create_release(
        self,
        repo: str,
        tag: str,
        notes: str,
        assets: list[str] | None = None,
        draft: bool = False,
        prerelease: bool = False,
        dry_run: bool = False,
        provenance_manifest: bool = False,
    ) -> dict[str, Any]:
        asset_checks, failed_assets = self._validate_assets(assets or [])
        provenance = self._provenance_manifest(asset_checks) if provenance_manifest else None

        if dry_run:
            return {
                "repo": repo,
                "tag": tag,
                "dry_run": True,
                "draft": draft,
                "prerelease": prerelease,
                "release_url": None,
                "release_id": None,
                "assets_requested": assets or [],
                "validated_assets": [item["path"] for item in asset_checks],
                "uploaded_assets": [],
                "failed_assets": failed_assets,
                "provenance": provenance,
            }

        release = self.github.create_release(
            repo=repo,
            tag=tag,
            notes=notes,
            name=tag,
            draft=draft,
            prerelease=prerelease,
        )

        upload_url = release.get("upload_url")
        uploaded_assets: list[dict[str, Any]] = []

        for checked in asset_checks:
            try:
                if not upload_url:
                    raise ValueError("Release upload URL missing from GitHub response")
                uploaded = self.github.upload_release_asset(
                    upload_url=upload_url,
                    file_path=checked["path"],
                    asset_name=checked["name"],
                    content_type=None,
                )
                uploaded_assets.append(
                    {
                        "id": uploaded.get("id"),
                        "name": uploaded.get("name"),
                        "size": uploaded.get("size"),
                        "download_url": uploaded.get("browser_download_url"),
                    }
                )
            except Exception as exc:
                failed_assets.append({"path": checked["path"], "error": str(exc)})

        return {
            "repo": repo,
            "tag": tag,
            "dry_run": False,
            "draft": draft,
            "prerelease": prerelease,
            "release_url": release.get("html_url"),
            "release_id": release.get("id"),
            "assets_requested": assets or [],
            "uploaded_assets": uploaded_assets,
            "failed_assets": failed_assets,
            "provenance": provenance,
        }

    def _resolve_expected_checksum(self, repo: str, checksum_source: str) -> str:
        if _HEX64_RE.match(checksum_source):
            return checksum_source.lower()

        if checksum_source.startswith("asset:"):
            checksum_asset_id = int(checksum_source.split(":", 1)[1])
            raw = self.github.download_release_asset(repo, checksum_asset_id).decode("utf-8", errors="ignore")
            first_token = raw.strip().split()[0]
            if _HEX64_RE.match(first_token):
                return first_token.lower()

        raise ValueError("checksum_source must be a 64-char hex digest or 'asset:<asset_id>'")

    @staticmethod
    def _find_previous_tag(releases: list[dict[str, Any]], to_tag: str | None) -> str | None:
        if not to_tag:
            return None
        for idx, release in enumerate(releases):
            if release.get("tag_name") == to_tag:
                if idx + 1 < len(releases):
                    return releases[idx + 1].get("tag_name")
                return None
        return None

    @staticmethod
    def _parse_commit_entries(
        commits: list[dict[str, Any]], repo: str, include_pr_links: bool
    ) -> list[dict[str, str]]:
        entries: list[dict[str, str]] = []
        for commit in commits:
            sha = commit.get("sha", "")[:7]
            message = commit.get("commit", {}).get("message", "").split("\n", 1)[0]
            prefix, scope = _parse_prefix_and_scope(message)
            author = commit.get("author", {}).get("login") or commit.get("commit", {}).get("author", {}).get("name", "unknown")
            rendered = message
            if include_pr_links:
                prs = sorted({int(value) for value in re.findall(r"#(\d+)", message)})
                if prs:
                    pr_links = ", ".join(f"[#{pr}](https://github.com/{repo}/pull/{pr})" for pr in prs)
                    rendered = f"{message} ({pr_links})"
            entries.append(
                {
                    "sha": sha,
                    "message": rendered,
                    "prefix": prefix,
                    "scope": scope or "unspecified",
                    "author": author,
                }
            )
        return entries

    @staticmethod
    def _build_notes_markdown(
        parsed_commits: list[dict[str, str]],
        from_tag: str | None,
        to_tag: str | None,
        fallback_used: bool,
        group_by: str = "type",
    ) -> str:
        lines = [
            "## Summary",
            f"- Range: {from_tag or 'N/A'} -> {to_tag or 'N/A'}",
            f"- Commits: {len(parsed_commits)}",
            f"- Fallback mode: {'yes' if fallback_used else 'no'}",
            "",
            "## Commits",
        ]

        for item in parsed_commits:
            lines.append(f"- {item['sha']}: {item['message']}")

        key_map = {
            "type": "prefix",
            "scope": "scope",
            "author": "author",
        }
        group_key = key_map.get(group_by)
        if group_key:
            grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
            for item in parsed_commits:
                grouped[item[group_key]].append(item)

            if grouped:
                heading = {
                    "type": "## By Type",
                    "scope": "## By Scope",
                    "author": "## By Author",
                }[group_by]
                lines.append("")
                lines.append(heading)
                for group_name in sorted(grouped.keys()):
                    lines.append(f"### {group_name}")
                    for item in grouped[group_name]:
                        lines.append(f"- {item['sha']}: {item['message']}")

        return "\n".join(lines)

    @staticmethod
    def _validate_assets(assets: list[str]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        valid: list[dict[str, Any]] = []
        failed: list[dict[str, Any]] = []
        for asset_path in assets:
            path = Path(asset_path)
            if not path.exists() or not path.is_file():
                failed.append({"path": str(path), "error": "File does not exist"})
                continue
            payload = path.read_bytes()
            valid.append(
                {
                    "path": str(path),
                    "name": path.name,
                    "size": len(payload),
                    "sha256": hashlib.sha256(payload).hexdigest(),
                }
            )
        return valid, failed

    @staticmethod
    def _provenance_manifest(valid_assets: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "version": "v1",
            "assets": [
                {
                    "path": item["path"],
                    "name": item["name"],
                    "size": item["size"],
                    "sha256": item["sha256"],
                }
                for item in valid_assets
            ],
        }


def _parse_prefix_and_scope(message: str) -> tuple[str, str | None]:
    matched = re.match(r"^([a-zA-Z0-9_-]+)(?:\(([^)]+)\))?!?:", message)
    if matched:
        prefix = matched.group(1).strip().lower()
        scope = matched.group(2).strip().lower() if matched.group(2) else None
        return prefix, scope
    return "other", None
