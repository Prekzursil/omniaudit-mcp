from __future__ import annotations

import asyncio
from pathlib import Path

from omniaudit.modules.sitelint import scanner


class _DummyResponse:
    status_code = 200
    text = "<html><head><title>Example</title></head><body>ok</body></html>"
    content = b"ok"


def test_run_sitelint_scan_is_event_loop_safe(monkeypatch, tmp_path: Path) -> None:
    def fake_get(*args, **kwargs) -> _DummyResponse:
        return _DummyResponse()

    def fake_capture(url: str, output_file: Path, auth_context: dict | None = None) -> str:
        output_file.write_bytes(b"png")
        return str(output_file)

    monkeypatch.setattr(scanner.httpx, "get", fake_get)
    monkeypatch.setattr(scanner, "_capture_screenshot", fake_capture)
    monkeypatch.setattr(scanner, "_run_lighthouse", lambda *args, **kwargs: None)
    monkeypatch.setattr(scanner, "_run_axe", lambda *args, **kwargs: None)

    async def _invoke() -> dict:
        return scanner.run_sitelint_scan(
            url="https://example.com",
            profile="standard",
            viewport_set="desktop_mobile",
            report_dir=tmp_path / "reports",
        )

    result = asyncio.run(_invoke())
    assert result["metrics"]["status_code"] == 200
    assert result["pages"][0]["screenshot"] is not None
