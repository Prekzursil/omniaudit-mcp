from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import httpx
from omniaudit.modules.sitelint import scanner as scanner_module
from omniaudit.modules.sitelint.scanner import (
    _build_scan_urls,
    _capture_screenshot,
    _extract_title,
    _host_from_url,
    _normalize_entry_paths,
    _run_axe,
    _run_lighthouse,
    run_sitelint_scan,
)


def test_host_and_title_helpers() -> None:
    assert _host_from_url("https://Example.com/path") == "example.com"
    assert _extract_title("<html><head><title>Hi</title></head></html>") == "Hi"
    assert _extract_title("<html>no title</html>") == ""
    # Tags present but empty/degenerate -> no extractable title.
    assert _extract_title("<title></title>") == ""


def test_normalize_entry_paths() -> None:
    assert _normalize_entry_paths(None) == ["/"]
    assert _normalize_entry_paths(["", "about", "/contact"]) == ["/", "/about", "/contact"]


def test_build_scan_urls_clamps_budget() -> None:
    urls = _build_scan_urls("https://x.com", crawl_budget=1, entry_paths=["/a", "/b"])
    assert len(urls) == 1
    # Budget None defaults to number of normalized paths.
    assert len(_build_scan_urls("https://x.com", crawl_budget=None, entry_paths=["/a"])) == 2


def test_capture_screenshot_returns_none_without_playwright(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setitem(sys.modules, "playwright.async_api", None)
    result = asyncio.run(_capture_screenshot("https://x.com", tmp_path / "s.png"))
    assert result is None


def test_run_lighthouse_success_and_failure(monkeypatch, tmp_path: Path) -> None:
    def fake_run(cmd, **kwargs):
        out = Path(cmd[-1].split("=", 1)[1])
        out.write_text(
            json.dumps(
                {
                    "categories": {
                        "performance": {"score": 0.9},
                        "accessibility": {"score": 0.8},
                        "best-practices": {"score": 0.7},
                        "seo": {"score": 0.6},
                    }
                }
            ),
            encoding="utf-8",
        )

    monkeypatch.setattr(scanner_module.subprocess, "run", fake_run)
    result = _run_lighthouse("https://x.com", tmp_path)
    assert result["seo"] == 0.6

    def boom(*a, **k):
        raise RuntimeError("no node")

    monkeypatch.setattr(scanner_module.subprocess, "run", boom)
    assert _run_lighthouse("https://x.com", tmp_path) is None


def test_run_axe_success_and_failure(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "axe.report.json"

    def fake_run(cmd, **kwargs):
        output.write_text(
            json.dumps({"violations": [1, 2], "incomplete": [], "passes": [1]}), encoding="utf-8"
        )

    monkeypatch.setattr(scanner_module.subprocess, "run", fake_run)
    result = _run_axe("https://x.com", tmp_path)
    assert result["violations"] == 2

    monkeypatch.setattr(
        scanner_module.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError())
    )
    assert _run_axe("https://x.com", tmp_path) is None


def test_run_sitelint_scan_full(monkeypatch, tmp_path: Path) -> None:
    def fake_get(url, **kwargs):
        # First page returns OK html with title; the explicit /missing path returns 404 + no title.
        if url.endswith("/missing"):
            return httpx.Response(404, text="<html></html>", request=httpx.Request("GET", url))
        return httpx.Response(200, text="<title>Home</title>", request=httpx.Request("GET", url))

    monkeypatch.setattr(scanner_module.httpx, "get", fake_get)
    monkeypatch.setattr(scanner_module, "_capture_screenshot", lambda *a, **k: asyncio_none())
    monkeypatch.setattr(
        scanner_module,
        "_run_lighthouse",
        lambda url, report_dir: {"seo": 0.5, "report_path": "lh.json"},
    )
    monkeypatch.setattr(
        scanner_module,
        "_run_axe",
        lambda url, report_dir: {"violations": 3, "report_path": "axe.json"},
    )

    report = run_sitelint_scan(
        "https://example.com",
        profile="standard",
        viewport_set="desktop_mobile",
        report_dir=tmp_path / "r",
        entry_paths=["/missing"],
        auth_context={"headers": {"Authorization": "Bearer x"}},
    )
    finding_ids = {f["finding_id"] for f in report["findings"]}
    assert "finding_low_lighthouse_seo" in finding_ids
    assert "finding_axe_violations" in finding_ids
    assert any(fid.startswith("finding_missing_title") for fid in finding_ids)
    assert any(fid.startswith("finding_bad_status") for fid in finding_ids)
    assert report["metrics"]["page_count"] == 2


def test_run_sitelint_scan_with_screenshot(monkeypatch, tmp_path: Path) -> None:
    def fake_get(url, **kwargs):
        return httpx.Response(200, text="<title>Home</title>", request=httpx.Request("GET", url))

    monkeypatch.setattr(scanner_module.httpx, "get", fake_get)
    monkeypatch.setattr(
        scanner_module, "_capture_screenshot", lambda *a, **k: asyncio_value("shot.png")
    )
    monkeypatch.setattr(scanner_module, "_run_lighthouse", lambda url, report_dir: {"seo": 0.95})
    monkeypatch.setattr(scanner_module, "_run_axe", lambda url, report_dir: {"violations": 0})

    report = run_sitelint_scan(
        "https://example.com",
        profile="standard",
        viewport_set="desktop_mobile",
        report_dir=tmp_path / "r2",
    )
    assert report["artifacts"]["screenshots"] == ["shot.png"]
    assert report["findings"] == []


async def _async_none():
    return None


async def _async_value(value):
    return value


def asyncio_none():
    return _async_none()


def asyncio_value(value):
    return _async_value(value)
