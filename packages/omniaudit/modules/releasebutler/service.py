from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from omniaudit.modules.github.client import GitHubClient
from omniaudit.modules.releasebutler.checksum import verify_checksum
from omniaudit.storage.base import ObjectStore

_HEX64_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(slots=True)
class ReleaseButlerService:
    github: GitHubClient
    object_store: ObjectStore | None = None

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
        template: str | None = None,
        max_commits: int | None = None,
        include_authors: bool = False,
        include_checks: bool = False,
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

        parsed = self._parse_commit_entries(
            compare_commits,
            repo=repo,
            include_pr_links=include_pr_links,
            include_authors=include_authors,
        )
        if max_commits is not None and max_commits > 0:
            parsed = parsed[: max(1, max_commits)]

        checks_summary = self._build_checks_summary(repo, compare_commits) if include_checks else None
        selected_group = (group_by or "type").strip().lower()
        selected_template = (template or "default").strip().lower()
        notes = self._build_notes_markdown(
            parsed,
            resolved_from,
            resolved_to,
            used_fallback,
            group_by=selected_group,
            template=selected_template,
            include_authors=include_authors,
        )

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
            "template": selected_template,
            "max_commits": max_commits,
            "include_authors": include_authors,
            "include_checks": include_checks,
            "checks_summary": checks_summary,
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
        channel: str | None = None,
        retry_failed_assets: bool = False,
        publish_timeout_seconds: int | None = None,
    ) -> dict[str, Any]:
        asset_checks, failed_assets = self._validate_assets(assets or [])
        provenance = self._provenance_manifest(asset_checks) if provenance_manifest else None
        provenance_ref = self.object_store.put_json_immutable(provenance) if provenance and self.object_store else None
        selected_channel = (channel or "stable").strip().lower()
        upload_attempts: list[dict[str, Any]] = []

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
                "provenance_ref": provenance_ref,
                "upload_attempts": [],
                "checks_summary": {
                    "channel": selected_channel,
                    "requested_assets": len(assets or []),
                    "validated_assets": len(asset_checks),
                    "failed_assets": len(failed_assets),
                },
            }

        notes_for_release = notes if selected_channel == "stable" else f"[{selected_channel}] {notes}"
        release = self.github.create_release(
            repo=repo,
            tag=tag,
            notes=notes_for_release,
            name=tag,
            draft=draft,
            prerelease=prerelease,
        )

        upload_url = release.get("upload_url")
        uploaded_assets: list[dict[str, Any]] = []

        for checked in asset_checks:
            max_attempts = 2 if retry_failed_assets else 1
            uploaded = None
            last_error: Exception | None = None
            for attempt in range(1, max_attempts + 1):
                try:
                    if not upload_url:
                        raise ValueError("Release upload URL missing from GitHub response")
                    uploaded = self.github.upload_release_asset(
                        upload_url=upload_url,
                        file_path=checked["path"],
                        asset_name=checked["name"],
                        content_type=None,
                        timeout_seconds=publish_timeout_seconds,
                    )
                    upload_attempts.append(
                        {
                            "path": checked["path"],
                            "asset_name": checked["name"],
                            "attempt": attempt,
                            "status": "success",
                        }
                    )
                    break
                except Exception as exc:
                    last_error = exc
                    upload_attempts.append(
                        {
                            "path": checked["path"],
                            "asset_name": checked["name"],
                            "attempt": attempt,
                            "status": "error",
                            "error": str(exc),
                        }
                    )
            if uploaded:
                uploaded_assets.append(
                    {
                        "id": uploaded.get("id"),
                        "name": uploaded.get("name"),
                        "size": uploaded.get("size"),
                        "download_url": uploaded.get("browser_download_url"),
                    }
                )
            elif last_error is not None:
                failed_assets.append({"path": checked["path"], "error": str(last_error)})

        return {
            "repo": repo,
            "tag": tag,
            "dry_run": False,
            "draft": draft,
            "prerelease": prerelease,
            "channel": selected_channel,
            "release_url": release.get("html_url"),
            "release_id": release.get("id"),
            "assets_requested": assets or [],
            "uploaded_assets": uploaded_assets,
            "failed_assets": failed_assets,
            "provenance": provenance,
            "provenance_ref": provenance_ref,
            "upload_attempts": upload_attempts,
            "checks_summary": {
                "channel": selected_channel,
                "requested_assets": len(assets or []),
                "validated_assets": len(asset_checks),
                "uploaded_assets": len(uploaded_assets),
                "failed_assets": len(failed_assets),
            },
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
        commits: list[dict[str, Any]],
        repo: str,
        include_pr_links: bool,
        include_authors: bool,
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
        template: str = "default",
        include_authors: bool = False,
    ) -> str:
        if template == "compact":
            lines = [
                f"Range: {from_tag or 'N/A'} -> {to_tag or 'N/A'}",
                f"Commits: {len(parsed_commits)} (fallback: {'yes' if fallback_used else 'no'})",
                "",
            ]
        else:
            lines = [
                "## Summary",
                f"- Range: {from_tag or 'N/A'} -> {to_tag or 'N/A'}",
                f"- Commits: {len(parsed_commits)}",
                f"- Fallback mode: {'yes' if fallback_used else 'no'}",
                "",
                "## Commits",
            ]

        for item in parsed_commits:
            author_suffix = f" ({item['author']})" if include_authors else ""
            lines.append(f"- {item['sha']}: {item['message']}{author_suffix}")

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

    def _build_checks_summary(self, repo: str, commits: list[dict[str, Any]]) -> dict[str, Any]:
        summary: dict[str, int] = {"success": 0, "failure": 0, "pending": 0, "error": 0}
        inspected = 0
        for commit in commits[:10]:
            sha = str(commit.get("sha", "")).strip()
            if not sha:
                continue
            inspected += 1
            try:
                status = self.github.get_commit_check_summary(repo, sha)
                state = str(status.get("state", "error")).lower()
                if state in summary:
                    summary[state] += 1
                else:
                    summary["error"] += 1
            except Exception:
                summary["error"] += 1
        return {"inspected_commits": inspected, "states": summary}

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
