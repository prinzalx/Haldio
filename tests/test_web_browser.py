"""Real browser test for the settings page (playwright + mock TTS).

Skipped by default; run it with: uv run pytest -m live
Needs no LM Studio and starts no real TTS model (backend `mock`).
"""

from __future__ import annotations

import socket
import threading
import time

import pytest
from uvicorn import Server
from uvicorn.config import Config as UvicornConfig

from haldio.config import Config
from haldio.jobs.index import JobIndex
from haldio.web.app import create_app

pytestmark = pytest.mark.live


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


@pytest.fixture()
def live_url(tmp_path):
    config = Config()
    config.paths.data_dir = tmp_path
    config.tts.backend = "mock"
    config.tts.confirm_before_start = False
    app = create_app(config, index=JobIndex(tmp_path / "index"))
    port = _free_port()
    server = Server(UvicornConfig(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 15
    import httpx

    while time.monotonic() < deadline:
        try:
            httpx.get(f"http://127.0.0.1:{port}/", timeout=1)
            break
        except httpx.TransportError:
            time.sleep(0.2)
    else:
        raise RuntimeError("test server did not start")
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=10)


def test_probe_button_click_uses_the_selected_voice(live_url, tmp_path) -> None:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        errors: list[str] = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(f"{live_url}/settings", wait_until="networkidle")
        page.click('input[name="tts.speaker"][value="vivian"]')
        page.fill("#f-probe-text", "Hallo Test")
        page.click("#probe-btn")
        page.wait_for_selector("#probe-result audio", timeout=15000)
        text = page.inner_text("#probe-result")
        browser.close()

    assert "Hörprobe fertig: Vivian" in text
    assert errors == []
    assert (tmp_path / "samples" / "vivian.wav").is_file()
