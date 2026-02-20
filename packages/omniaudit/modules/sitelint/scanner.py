from __future__ import annotations

import asyncio
import fnmatch
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx


@dataclass(slots=True)
class SiteLintProfile:
    profile: str
    viewport_set: str


async def _capture_screenshot(url: str, output_file: Path, auth_context: dict[str, Any] | None = None) -> str | None:
    try:
        from playwright.async_api import async_playwright
    except Exception:
        return None

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        context = await browser.new_context(viewport={"width": 1280, "height": 720})
        if auth_context and isinstance(auth_context.get("cookies"), list):
            try:
                await context.add_cookies(auth_context["cookies"])
            except Exception:
                pass
        page = await context.new_page()
        if auth_context and isinstance(auth_context.get("headers"), dict):
            try:
                await page.set_extra_http_headers(auth_context["headers"])
            except Exception:
                pass
        await page.goto(url, wait_until="networkidle", timeout=45000)
        await page.screenshot(path=str(output_file), full_page=True)
        await context.close()
        await browser.close()
    return str(output_file)


def _run_lighthouse(url: str, report_dir: Path) -> dict[str, Any] | None:
    output = report_dir / "lighthouse.report.json"
    command = [
        "npx",
        "--yes",
        "lighthouse",
        url,
        "--quiet",
        "--chrome-flags=--headless",
        "--output=json",
        f"--output-path={output}",
    ]
    try:
        subprocess.run(command, check=True, timeout=180, capture_output=True, text=True)
        payload = json.loads(output.read_text(encoding="utf-8"))
        categories = payload.get("categories", {})
        return {
            "performance": categories.get("performance", {}).get("score"),
            "accessibility": categories.get("accessibility", {}).get("score"),
            "best_practices": categories.get("best-practices", {}).get("score"),
            "seo": categories.get("seo", {}).get("score"),
            "report_path": str(output),
        }
    except Exception:
        return None


def _run_axe(url: str, report_dir: Path) -> dict[str, Any] | None:
    output = report_dir / "axe.report.json"
    node_script = f"""
const fs = require('fs');
const {{ chromium }} = require('playwright');
const axe = require('axe-core');

(async () => {{
  const browser = await chromium.launch({{ headless: true }});
  const page = await browser.newPage({{ viewport: {{ width: 1280, height: 720 }} }});
  await page.goto('{url}', {{ waitUntil: 'networkidle', timeout: 45000 }});
  await page.addScriptTag({{ content: axe.source }});
  const results = await page.evaluate(async () => await axe.run());
  fs.writeFileSync('{output.as_posix()}', JSON.stringify(results));
  await browser.close();
}})().catch(err => {{
  console.error(err);
  process.exit(1);
}});
"""
    try:
        subprocess.run(["node", "-e", node_script], check=True, timeout=180, capture_output=True, text=True)
        payload = json.loads(output.read_text(encoding="utf-8"))
        return {
            "violations": len(payload.get("violations", [])),
            "incomplete": len(payload.get("incomplete", [])),
            "passes": len(payload.get("passes", [])),
            "report_path": str(output),
        }
    except Exception:
        return None


def _host_from_url(url: str) -> str:
    return urlparse(url).netloc.lower()


def _extract_title(html: str) -> str:
    title = ""
    if "<title" in html.lower() and "</title>" in html.lower():
        lower = html.lower()
        start = lower.find("<title")
        start = lower.find(">", start) + 1
        end = lower.find("</title>", start)
        if start > 0 and end > start:
            title = html[start:end].strip()
    return title


def _normalize_entry_paths(entry_paths: list[str] | None) -> list[str]:
    if not entry_paths:
        return ["/"]
    cleaned = {"/"}
    for path in entry_paths:
        value = (path or "").strip()
        if not value:
            continue
        if not value.startswith("/"):
            value = f"/{value}"
        cleaned.add(value)
    return sorted(cleaned)


def _build_scan_urls(base_url: str, crawl_budget: int | None, entry_paths: list[str] | None) -> list[str]:
    normalized = _normalize_entry_paths(entry_paths)
    urls = [urljoin(f"{base_url.rstrip('/')}/", path.lstrip("/")) for path in normalized]
    budget = crawl_budget if crawl_budget is not None else len(urls)
    budget = max(1, min(int(budget), 25))
    return urls[:budget]


def _path_depth(path_or_url: str) -> int:
    parsed = urlparse(path_or_url)
    segments = [segment for segment in parsed.path.split("/") if segment]
    return len(segments)


def _matches_patterns(path_or_url: str, patterns: list[str] | None) -> bool:
    if not patterns:
        return True
    parsed = urlparse(path_or_url)
    value = parsed.path or "/"
    return any(fnmatch.fnmatch(value, pattern) for pattern in patterns)


def _build_scan_urls_v2(
    base_url: str,
    crawl_budget: int | None,
    entry_paths: list[str] | None,
    *,
    max_depth: int | None = None,
    crawl_strategy: str = "bfs",
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
) -> list[str]:
    urls = _build_scan_urls(base_url, crawl_budget=crawl_budget, entry_paths=entry_paths)

    filtered: list[str] = []
    for page_url in urls:
        if max_depth is not None and _path_depth(page_url) > max(0, int(max_depth)):
            continue
        if not _matches_patterns(page_url, include_patterns):
            continue
        if exclude_patterns and _matches_patterns(page_url, exclude_patterns):
            continue
        filtered.append(page_url)

    if not filtered:
        filtered = [urljoin(f"{base_url.rstrip('/')}/", "")]

    strategy = (crawl_strategy or "bfs").strip().lower()
    if strategy == "dfs":
        filtered.sort(key=lambda item: (-_path_depth(item), item))
    else:
        filtered.sort(key=lambda item: (_path_depth(item), item))

    return filtered


def run_sitelint_scan(
    url: str,
    profile: str,
    viewport_set: str,
    report_dir: Path,
    *,
    crawl_budget: int | None = None,
    entry_paths: list[str] | None = None,
    auth_context: dict[str, Any] | None = None,
    max_depth: int | None = None,
    crawl_strategy: str = "bfs",
    include_patterns: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    capture_console: bool = False,
    capture_network: bool = False,
    auth_journey_id: str | None = None,
) -> dict[str, Any]:
    report_dir.mkdir(parents=True, exist_ok=True)

    headers = {}
    if auth_context and isinstance(auth_context.get("headers"), dict):
        headers = {str(k): str(v) for k, v in auth_context["headers"].items()}

    scan_urls = _build_scan_urls_v2(
        url,
        crawl_budget=crawl_budget,
        entry_paths=entry_paths,
        max_depth=max_depth,
        crawl_strategy=crawl_strategy,
        include_patterns=include_patterns,
        exclude_patterns=exclude_patterns,
    )
    pages: list[dict[str, Any]] = []
    screenshots: list[str] = []
    findings: list[dict[str, Any]] = []
    response_times: list[int] = []
    console_snapshots: list[dict[str, Any]] = []
    network_snapshots: list[dict[str, Any]] = []

    for idx, page_url in enumerate(scan_urls):
        started = time.perf_counter()
        response = httpx.get(page_url, timeout=30.0, follow_redirects=True, headers=headers)
        duration_ms = int((time.perf_counter() - started) * 1000)
        response_times.append(duration_ms)

        title = _extract_title(response.text)
        screenshot_path = report_dir / f"page-{idx + 1}.png"
        screenshot_ref = asyncio.run(_capture_screenshot(page_url, screenshot_path, auth_context=auth_context))
        if screenshot_ref:
            screenshots.append(screenshot_ref)

        page_findings: list[dict[str, Any]] = []
        if not title:
            page_findings.append(
                {
                    "finding_id": f"finding_missing_title_{idx + 1}",
                    "severity": "s2",
                    "category": "seo",
                    "title": "Missing title tag",
                    "confidence": 0.95,
                    "suggested_fix": "Add a unique <title> element.",
                    "evidence_refs": [{"source_type": "http", "path_or_url": page_url}],
                }
            )
        if response.status_code >= 400:
            page_findings.append(
                {
                    "finding_id": f"finding_bad_status_{idx + 1}",
                    "severity": "s1",
                    "category": "correctness",
                    "title": f"HTTP {response.status_code} on requested URL",
                    "confidence": 1.0,
                    "suggested_fix": "Fix route availability and server response.",
                    "evidence_refs": [{"source_type": "http", "path_or_url": page_url}],
                }
            )

        page_console: list[dict[str, Any]] = []
        if capture_console:
            if not title:
                page_console.append({"level": "warn", "message": "Missing title tag", "url": page_url})
            if response.status_code >= 400:
                page_console.append(
                    {"level": "error", "message": f"HTTP {response.status_code} response", "url": page_url}
                )

        page_network: list[dict[str, Any]] = []
        if capture_network:
            page_network.append(
                {
                    "url": page_url,
                    "method": "GET",
                    "status_code": response.status_code,
                    "duration_ms": duration_ms,
                    "content_length": len(response.content),
                }
            )

        pages.append(
            {
                "url": page_url,
                "status_code": response.status_code,
                "response_time_ms": duration_ms,
                "content_length": len(response.content),
                "title": title,
                "screenshot": screenshot_ref,
                "findings": page_findings,
                "console": page_console,
                "network": page_network,
            }
        )
        findings.extend(page_findings)
        if page_console:
            console_snapshots.append({"url": page_url, "events": page_console})
        if page_network:
            network_snapshots.append({"url": page_url, "events": page_network})

    lighthouse = _run_lighthouse(url, report_dir)
    axe = _run_axe(url, report_dir)

    if lighthouse and lighthouse.get("seo") is not None and float(lighthouse["seo"]) < 0.8:
        findings.append(
            {
                "finding_id": "finding_low_lighthouse_seo",
                "severity": "s3",
                "category": "seo",
                "title": "Lighthouse SEO score below target threshold",
                "confidence": 0.8,
                "suggested_fix": "Review Lighthouse SEO diagnostics and improve page metadata/semantics.",
                "evidence_refs": [{"source_type": "lighthouse", "path_or_url": str(lighthouse.get("report_path"))}],
            }
        )
    if axe and int(axe.get("violations", 0)) > 0:
        findings.append(
            {
                "finding_id": "finding_axe_violations",
                "severity": "s2",
                "category": "accessibility",
                "title": f"axe-core reported {axe.get('violations')} accessibility violations",
                "confidence": 0.9,
                "suggested_fix": "Inspect axe-core report and resolve high-impact rule failures first.",
                "evidence_refs": [{"source_type": "axe", "path_or_url": str(axe.get("report_path"))}],
            }
        )

    crawl_graph = {
        "strategy": (crawl_strategy or "bfs").strip().lower(),
        "max_depth": max_depth,
        "nodes": [{"id": page_url, "depth": _path_depth(page_url)} for page_url in scan_urls],
        "edges": [{"from": url, "to": page_url} for page_url in scan_urls if page_url != url],
    }

    report: dict[str, Any] = {
        "url": url,
        "host": _host_from_url(url),
        "profile": profile,
        "viewport_set": viewport_set,
        "auth_journey_id": auth_journey_id,
        "crawl_strategy": (crawl_strategy or "bfs").strip().lower(),
        "max_depth": max_depth,
        "include_patterns": include_patterns or [],
        "exclude_patterns": exclude_patterns or [],
        "capture_console": capture_console,
        "capture_network": capture_network,
        "crawl_budget": len(scan_urls),
        "entry_paths": _normalize_entry_paths(entry_paths),
        "pages": pages,
        "metrics": {
            "status_code": pages[0]["status_code"] if pages else None,
            "response_time_ms": pages[0]["response_time_ms"] if pages else None,
            "content_length": pages[0]["content_length"] if pages else None,
            "title": pages[0]["title"] if pages else "",
            "page_count": len(pages),
            "avg_response_time_ms": int(sum(response_times) / len(response_times)) if response_times else 0,
        },
        "artifacts": {
            "screenshot": pages[0]["screenshot"] if pages else None,
            "screenshots": screenshots,
            "screenshot_index": [
                {"url": item["url"], "path": item["screenshot"]}
                for item in pages
                if item.get("screenshot")
            ],
            "lighthouse": lighthouse,
            "axe": axe,
            "console_snapshots": console_snapshots,
            "network_snapshots": network_snapshots,
            "notes": "Lighthouse and axe-core run when node toolchain is installed; otherwise they are null.",
        },
        "crawl_graph": crawl_graph,
        "findings": findings,
    }
    return report
