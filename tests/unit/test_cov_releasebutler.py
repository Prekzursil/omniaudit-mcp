from __future__ import annotations

import hashlib

import pytest
from omniaudit.modules.releasebutler.service import ReleaseButlerService, _parse_prefix_and_scope

from tests.conftest import FakeGitHub


def _svc(**gh):
    return ReleaseButlerService(github=FakeGitHub(**gh))


def test_get_latest_and_list_assets() -> None:
    release = {
        "tag_name": "v1",
        "name": "Release 1",
        "published_at": "2026-01-01",
        "html_url": "u",
        "assets": [{"id": 1, "name": "a.zip", "size": 5, "download_count": 2}],
    }
    svc = _svc(get_latest_release=release, get_release_by_tag=release)
    latest = svc.get_latest("o/r")
    assert latest["tag"] == "v1"
    by_tag = svc.list_assets("o/r", tag="v1")
    assert by_tag["assets"][0]["name"] == "a.zip"
    # Without a tag, falls back to latest release.
    assert svc.list_assets("o/r")["tag"] == "v1"


def test_verify_asset_hex_and_asset_source() -> None:
    content = b"binary-data"
    digest = hashlib.sha256(content).hexdigest()
    svc = _svc(download_release_asset=content)
    assert svc.verify_asset("o/r", 1, digest)["verified"] is True

    # asset:<id> source -> downloads checksum text then verifies.
    checksum_text = f"{digest}  artifact.zip"
    svc2 = _svc(download_release_asset=content)

    def fake_download(repo, asset_id):
        return content if asset_id == 1 else checksum_text.encode("utf-8")

    svc2.github.download_release_asset = fake_download  # type: ignore[method-assign]
    assert svc2.verify_asset("o/r", 1, "asset:2")["verified"] is True


def test_verify_asset_invalid_source() -> None:
    svc = _svc(download_release_asset=b"x")
    with pytest.raises(ValueError, match="64-char hex digest"):
        svc.verify_asset("o/r", 1, "not-a-checksum")


def test_verify_asset_source_with_non_hex_token() -> None:
    svc = _svc()

    def fake_download(repo, asset_id):
        return b"garbage-not-hex" if asset_id == 9 else b"data"

    svc.github.download_release_asset = fake_download  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="64-char hex digest"):
        svc.verify_asset("o/r", 1, "asset:9")


def test_generate_notes_with_compare_and_groupings() -> None:
    releases = [{"tag_name": "v2"}, {"tag_name": "v1"}]
    commits = [
        {
            "sha": "abcdef1",
            "commit": {"message": "feat(api): add #12"},
            "author": {"login": "alice"},
        },
        {"sha": "1234567", "commit": {"message": "fix: bug", "author": {"name": "bob"}}},
    ]
    svc = _svc(list_releases=releases, compare_commits={"commits": commits})
    out = svc.generate_notes("o/r", tag=None, group_by="type", include_pr_links=True)
    assert out["range"]["fallback_used"] is False
    assert out["range"]["from_tag"] == "v1"
    assert out["range"]["to_tag"] == "v2"
    assert "## By Type" in out["notes"]
    assert "pull/12" in out["notes"]

    out_scope = svc.generate_notes("o/r", tag="v2", from_tag="v1", to_tag="v2", group_by="scope")
    assert "## By Scope" in out_scope["notes"]
    out_author = svc.generate_notes("o/r", tag="v2", from_tag="v1", to_tag="v2", group_by="author")
    assert "## By Author" in out_author["notes"]
    out_none = svc.generate_notes("o/r", tag="v2", from_tag="v1", to_tag="v2", group_by="invalid")
    assert "## By" not in out_none["notes"]


def test_generate_notes_fallback_when_compare_fails() -> None:
    releases = [{"tag_name": "v2"}, {"tag_name": "v1"}]
    svc = _svc(
        list_releases=releases,
        compare_commits=RuntimeError("compare failed"),
        list_commits=[{"sha": "deadbee", "commit": {"message": "chore: x"}}],
    )
    out = svc.generate_notes("o/r", tag=None, fallback_window=5)
    assert out["range"]["fallback_used"] is True
    assert out["range"]["commit_count"] == 1


def test_generate_notes_fallback_when_no_range() -> None:
    # No releases -> no resolved range -> fallback to recent commits.
    svc = _svc(list_releases=[], list_commits=[{"sha": "f00ba12", "commit": {"message": "x"}}])
    out = svc.generate_notes("o/r", tag=None)
    assert out["range"]["fallback_used"] is True


def test_create_release_dry_run_with_provenance(tmp_path) -> None:
    asset = tmp_path / "a.bin"
    asset.write_bytes(b"data")
    svc = _svc()
    out = svc.create_release(
        "o/r", "v1", "notes", assets=[str(asset)], dry_run=True, provenance_manifest=True
    )
    assert out["dry_run"] is True
    assert out["validated_assets"] == [str(asset)]
    assert out["provenance"]["assets"][0]["name"] == "a.bin"


def test_create_release_uploads_assets_and_records_failures(tmp_path) -> None:
    good = tmp_path / "good.bin"
    good.write_bytes(b"ok")
    missing = tmp_path / "missing.bin"  # never created -> validation failure
    svc = _svc(
        create_release={"upload_url": "https://uploads/x{?name}", "html_url": "u", "id": 3},
        upload_release_asset={"id": 1, "name": "good.bin", "size": 2, "browser_download_url": "d"},
    )
    out = svc.create_release("o/r", "v1", "notes", assets=[str(good), str(missing)])
    assert out["dry_run"] is False
    assert out["uploaded_assets"][0]["name"] == "good.bin"
    assert any(f["path"] == str(missing) for f in out["failed_assets"])


def test_create_release_upload_failure_when_no_upload_url(tmp_path) -> None:
    good = tmp_path / "good.bin"
    good.write_bytes(b"ok")
    svc = _svc(create_release={"html_url": "u", "id": 3})  # no upload_url
    out = svc.create_release("o/r", "v1", "notes", assets=[str(good)])
    assert out["uploaded_assets"] == []
    assert "upload URL missing" in out["failed_assets"][0]["error"]


def test_find_previous_tag_edge_cases() -> None:
    svc = _svc(list_releases=[{"tag_name": "only"}], compare_commits={"commits": []})
    # to_tag is the last release -> no previous tag -> fallback path.
    out = svc.generate_notes("o/r", tag="only")
    assert out["range"]["from_tag"] is None


def test_find_previous_tag_no_match_in_releases() -> None:
    # resolved_to ("v9") is not present in releases -> loop exhausts, returns None.
    svc = _svc(
        list_releases=[{"tag_name": "v2"}, {"tag_name": "v1"}],
        list_commits=[{"sha": "abc1234", "commit": {"message": "x"}}],
    )
    out = svc.generate_notes("o/r", tag="v9")
    assert out["range"]["from_tag"] is None
    assert out["range"]["fallback_used"] is True


def test_parse_prefix_and_scope() -> None:
    assert _parse_prefix_and_scope("feat(api): x") == ("feat", "api")
    assert _parse_prefix_and_scope("feat: x") == ("feat", None)
    assert _parse_prefix_and_scope("no convention here") == ("other", None)
