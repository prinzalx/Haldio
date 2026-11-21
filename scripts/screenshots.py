"""Make the Correction 6 screenshots (mock data only, no TTS model is started).

Builds the eight scenarios the spec lists (editing with live detail, waiting
for the LLM unload, speaking, failed, finished, review with one empty
section, library with three jobs, settings), serves the real app on a free
port and captures each page in the light and the dark theme into
docs/screenshots/. Width checks at 360, 768 and 1280 px are captured too and
printed as overflow checks.

Run: .venv\\Scripts\\python.exe scripts\\screenshots.py
"""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
import threading
import time
import wave
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402
from fastapi import FastAPI  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from haldio.config import load_config  # noqa: E402
from haldio.jobs.index import JobIndex  # noqa: E402
from haldio.web.app import create_app  # noqa: E402

OUT = ROOT / "docs" / "screenshots"
WIDTHS = (360, 768, 1280)


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _wav_bytes(seconds: float = 1.0, rate: int = 24000) -> bytes:
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def _activity(state: str, stage: str, done: int, total: int, detail: str) -> dict:
    return {
        "state": state,
        "stage": stage,
        "done": done,
        "total": total,
        "detail": detail,
        "eta": None,
        "updated_at": _now(),
    }


def _seed_library(index: JobIndex) -> dict[str, str]:
    """The six job pages plus the review job, all as mock state."""
    ids: dict[str, str] = {}

    editing = index.create("entwurf.pdf")
    editing.title = "Entwurf der Arbeitsregelung"
    editing.status = "editing"
    editing.progress = 34
    editing.page_count = 36
    editing.message = "das Sprachmodell schreibt seit 38 s (etwa 410 Token)"
    editing.activity = _activity(
        "running",
        "editing",
        3,
        9,
        "das Sprachmodell schreibt seit 38 s (etwa 410 Token)",
    )
    editing.logs = [
        "10:12:03 [INFO] Einlesen: 36 Seiten gelesen",
        "10:12:40 [INFO] Planen: 9 Abschnitte geplant",
        "10:13:02 [INFO] Hörtext schreiben: Abschnitt 1/9 fertig nach 21 s",
        "10:13:24 [INFO] Hörtext schreiben: Abschnitt 2/9 fertig nach 22 s",
    ]
    index.update(editing)
    ids["editing"] = editing.id

    unload = index.create("poller.pdf")
    unload.title = "Handbuch der Prozesse"
    unload.status = "waiting_for_user"
    unload.progress = 62
    unload.page_count = 88
    unload.message = "Bitte das LLM in LM Studio entladen, dann Weiter drücken."
    unload.error = "Qwen3-TTS passt nicht in den Speicher, solange das LLM geladen ist."
    unload.activity = _activity("waiting", "speaking", 0, 0, unload.message)
    index.update(unload)
    ids["unload"] = unload.id

    speaking = index.create("handbuch.pdf")
    speaking.title = "Handbuch der Technik"
    speaking.status = "speaking"
    speaking.progress = 66
    speaking.message = "Einheit 12 von 957 · noch etwa 42 min"
    speaking.page_count = 120
    speaking.activity = _activity(
        "running", "speaking", 12, 957, "Einheit 12 von 957 · noch etwa 42 min"
    )
    speaking.logs = [
        "10:31:47 [INFO] Vorlesen: gestartet",
        "10:32:02 [INFO] Vorlesen: Einheit 1/957 fertig nach 15 s",
        "10:41:55 [INFO] Vorlesen: Einheit 12/957 fertig nach 51 s",
    ]
    index.update(speaking)
    ids["speaking"] = speaking.id

    failed = index.create("fibel.pdf")
    failed.title = "Fibel der Lautsprache"
    failed.status = "failed"
    failed.progress = 66
    failed.page_count = 54
    failed.message = "Vorlesen fehlgeschlagen."
    failed.error = "LLM call failed: Connection error."
    failed.error_detail = "httpx.ConnectError: [WinError 10061] Connection refused"
    failed.activity = _activity("failed", "speaking", 0, 0, failed.message)
    index.update(failed)
    ids["failed"] = failed.id

    done = index.create("buch.pdf")
    done.title = "Mein Buch"
    done.status = "done"
    done.progress = 100
    done.message = "Fertig."
    done.page_count = 96
    done.audio_seconds = 4320
    done.activity = _activity("done", "mastering", 0, 0, "Fertig.")
    index.update(done)
    ids["done"] = done.id
    job_dir = index.jobs_dir / done.id
    (job_dir / "06_master").mkdir(parents=True, exist_ok=True)
    (job_dir / "06_master" / "book.mp3").write_bytes(_wav_bytes(2.0))
    (job_dir / "06_master" / "book.ogg").write_bytes(b"OggS\x00\x02fake")
    (job_dir / "04_script").mkdir(parents=True, exist_ok=True)
    (job_dir / "04_script" / "script.md").write_text(
        "# Mein Buch\n\nFertiges Skript.\n", encoding="utf-8"
    )
    (job_dir / "04_script" / "qa_report.html").write_text(
        "<html><body>QA</body></html>", encoding="utf-8"
    )
    (job_dir / "source.pdf").write_bytes(b"%PDF-1.4 fake")
    (job_dir / "02_plan").mkdir(parents=True, exist_ok=True)
    (job_dir / "02_plan" / "doc_map.json").write_text(
        json.dumps(
            {
                "title": "Mein Buch",
                "language": "de",
                "page_count": 96,
                "summary": "Eine Reise durch die Audio-Technik.",
                "main_topics": ["Aufnahme", "Mischung", "Mastering"],
                "estimated_audio_seconds": 4200,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    review = index.create("kapitel.pdf")
    review.title = "Kapitelprobe"
    review.status = "awaiting_review"
    review.progress = 60
    review.page_count = 12
    review.activity = _activity("waiting", "script", 0, 0, "Skript wartet auf Prüfung")
    index.update(review)
    ids["review"] = review.id
    rdir = index.jobs_dir / review.id / "04_script"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "script.json").write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "chunk_id": "c0001",
                        "blocks": [
                            {"kind": "heading", "level": 1, "text": "Erstes Kapitel"},
                            {"kind": "paragraph", "text": "Der edierte Text des ersten Absatzes."},
                        ],
                        "warnings": [
                            {"type": "unclear_source", "detail": " Absatz 2 war schwer lesbar."}
                        ],
                        "needs_review": True,
                    },
                    {
                        "chunk_id": "c0002",
                        "blocks": [
                            {"kind": "paragraph", "text": "Ein zweiter, unauffälliger Absatz."}
                        ],
                        "warnings": [],
                        "needs_review": False,
                    },
                    {"chunk_id": "c0003", "blocks": [], "warnings": [], "needs_review": False},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cdir = index.jobs_dir / review.id / "03_edit" / "chunks"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "c0001.in.json").write_text(
        json.dumps(
            {
                "chunk_id": "c0001",
                "chapter_path": "Erstes Kapitel > Anfänge",
                "blocks": [
                    {"type": "heading", "text": "1 Erstes Kapitel", "level": 1},
                    {"type": "paragraph", "text": "Originaltext des ersten Absatzes aus dem PDF."},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (cdir / "c0002.in.json").write_text(
        json.dumps(
            {
                "chunk_id": "c0002",
                "chapter_path": "Erstes Kapitel > Anfänge",
                "blocks": [{"type": "paragraph", "text": "Originaltext des zweiten Absatzes."}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (cdir / "c0003.in.json").write_text(
        json.dumps(
            {
                "chunk_id": "c0003",
                "chapter_path": "Erstes Kapitel > Ende",
                "blocks": [
                    {
                        "type": "table",
                        "text": " ",
                        "cells": [["Schritt", "Zeit"], ["Test", "3 min"]],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return ids


def _seed_three_jobs(index: JobIndex) -> None:
    """Exactly three jobs for the library screenshot (one waiting for TTS)."""
    pool = index.create("aufsatz.pdf")
    pool.title = "Aufsatz über Sprache"
    pool.status = "awaiting_tts"
    pool.progress = 60
    pool.page_count = 18
    index.update(pool)

    done = index.create("buch.pdf")
    done.title = "Mein Buch"
    done.status = "done"
    done.progress = 100
    done.page_count = 96
    done.audio_seconds = 4320
    index.update(done)

    speaking = index.create("handbuch.pdf")
    speaking.title = "Handbuch der Technik"
    speaking.status = "speaking"
    speaking.progress = 66
    speaking.page_count = 120
    speaking.activity = _activity(
        "running", "speaking", 12, 957, "Einheit 12 von 957 · noch etwa 42 min"
    )
    index.update(speaking)


def _serve(app: FastAPI, port: int) -> tuple[uvicorn.Server, threading.Thread]:
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    while not server.started:
        time.sleep(0.1)
    return server, thread


PAGE_URLS: dict[str, str] = {}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    data_dir = Path(tempfile.mkdtemp(prefix="haldio-shots-"))
    lib_dir = Path(tempfile.mkdtemp(prefix="haldio-lib-"))
    try:
        config = load_config(ROOT / "config.yaml")
        config.tts.backend = "mock"  # never start a TTS model for screenshots

        config.paths.data_dir = data_dir
        index = JobIndex(data_dir)
        app = create_app(config, index=index)
        ids = _seed_library(index)

        config.paths.data_dir = lib_dir
        lib_index = JobIndex(lib_dir)
        lib_app = create_app(config, index=lib_index)  # worker starts on an empty index
        _seed_three_jobs(lib_index)

        global PAGE_URLS
        PAGE_URLS = {
            "job_editing": f"/jobs/{ids['editing']}",
            "job_llm_unload": f"/jobs/{ids['unload']}",
            "job_speaking": f"/jobs/{ids['speaking']}",
            "job_failed": f"/jobs/{ids['failed']}",
            "job_finished": f"/jobs/{ids['done']}",
            "review": f"/jobs/{ids['review']}/review",
            "library": "/",
            "settings": "/settings",
        }

        server1, thread1 = _serve(app, 8765)
        server2, thread2 = _serve(lib_app, 8766)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            for name in PAGE_URLS:
                base = "http://127.0.0.1:8766" if name == "library" else "http://127.0.0.1:8765"
                for theme in ("light", "dark"):
                    page.emulate_media(color_scheme=theme)
                    page.goto(f"{base}{PAGE_URLS[name]}")
                    page.wait_for_timeout(400)
                    target = OUT / f"{name}_{theme}.png"
                    page.screenshot(path=str(target), full_page=True)
                    print(f"{target.name}: {target.stat().st_size:,} bytes")

            # width checks: no horizontal overflow at 360 / 768 / 1280 px
            for width in WIDTHS:
                page.set_viewport_size({"width": width, "height": 900})
                for label, base, url in (
                    ("library", "http://127.0.0.1:8766", "/"),
                    ("job_editing", "http://127.0.0.1:8765", PAGE_URLS["job_editing"]),
                ):
                    page.emulate_media(color_scheme="light")
                    page.goto(f"{base}{url}")
                    page.wait_for_timeout(300)
                    overflow = page.evaluate(
                        "document.documentElement.scrollWidth >"
                        " document.documentElement.clientWidth"
                    )
                    target = OUT / f"width{width}_{label}_light.png"
                    page.screenshot(path=str(target), full_page=True)
                    print(f"width {width} px @ {label}: overflow={overflow}")
            browser.close()
        server1.should_exit = True
        server2.should_exit = True
        thread1.join(timeout=10)
        thread2.join(timeout=10)
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
        shutil.rmtree(lib_dir, ignore_errors=True)
    print("SCREENSHOTS-OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
