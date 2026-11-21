"""Make the Correction 4 screenshots (mock data only, no TTS model is started).

Builds a small in-memory library (running job, finished job, pool job, review
job), serves the real app on a free port and captures four pages in the light
and the dark theme into docs/screenshots/.

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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import uvicorn  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from haldio.config import load_config  # noqa: E402
from haldio.jobs.index import JobIndex  # noqa: E402
from haldio.web.app import create_app  # noqa: E402

OUT = ROOT / "docs" / "screenshots"


def _wav_bytes(seconds: float = 1.0, rate: int = 24000) -> bytes:
    import io

    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def _seed(index: JobIndex) -> dict[str, str]:
    """Create the four screenshot jobs directly in the index (no pipeline run)."""
    folder = index.jobs_dir
    ids: dict[str, str] = {}

    running = index.create("handbuch.pdf", options={"stage": "speaking"})
    running.title = "Handbuch der Technik"
    running.status = "speaking"
    running.progress = 66
    running.message = "Einheit 12 von 957 · noch etwa 42 min"
    running.page_count = 120
    running.logs = [
        "10:12:03 editing 42%",
        "10:31:47 speaking 65%",
        "10:32:02 speaking 65% 1/957",
        "10:41:55 speaking 66% 12/957",
    ]
    index.update(running)
    ids["running"] = running.id

    done = index.create("buch.pdf")
    done.title = "Mein Buch"
    done.status = "done"
    done.progress = 100
    done.message = "Fertig"
    done.page_count = 96
    done.audio_seconds = 4320
    index.update(done)
    ids["done"] = done.id
    job_dir = folder / done.id
    (job_dir / "06_master").mkdir(parents=True, exist_ok=True)
    (job_dir / "06_master" / "book.mp3").write_bytes(_wav_bytes(2.0))
    (job_dir / "06_master" / "book.ogg").write_bytes(b"OggS\x00\x02fake")
    (job_dir / "04_script").mkdir(parents=True, exist_ok=True)
    (job_dir / "04_script" / "script.md").write_text("# Mein Buch\n\nFertiges Skript.\n", encoding="utf-8")
    (job_dir / "04_script" / "qa_report.html").write_text("<html><body>QA</body></html>", encoding="utf-8")
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

    pool = index.create("aufsatz.pdf")
    pool.title = "Aufsatz über Sprache"
    pool.status = "awaiting_tts"
    pool.progress = 60
    pool.message = "Bereit für Sprachausgabe"
    pool.page_count = 18
    index.update(pool)
    ids["pool"] = pool.id

    review = index.create("kapitel.pdf")
    review.status = "awaiting_review"
    review.progress = 60
    review.page_count = 12
    index.update(review)
    ids["review"] = review.id
    rdir = folder / review.id / "04_script"
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "script.json").write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "chunk_id": "c0001",
                        "blocks": [
                            {"kind": "heading", "level": 1, "text": "Erstes Kapitel"},
                            {"kind": "paragraph", "text": "Der edtierte Text des ersten Absatzes."},
                        ],
                        "warnings": [{"type": "unclear_source", "detail": " Absatz 2 war schwer lesbar."}],
                        "needs_review": True,
                    },
                    {
                        "chunk_id": "c0002",
                        "blocks": [{"kind": "paragraph", "text": "Ein zweiter, unauffälliger Absatz."}],
                        "warnings": [],
                        "needs_review": False,
                    },
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    cdir = folder / review.id / "03_edit" / "chunks"
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
    return ids


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    data_dir = Path(tempfile.mkdtemp(prefix="haldio-shots-"))
    try:
        config = load_config(ROOT / "config.yaml")
        config.paths.data_dir = data_dir
        config.tts.backend = "mock"  # never start a TTS model for screenshots
        index = JobIndex(data_dir)
        app = create_app(config, index=index)  # worker thread starts on an empty index
        ids = _seed(index)

        server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="error"))
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        while not server.started:
            time.sleep(0.1)

        pages = {
            "library": "/",
            "job_running": f"/jobs/{ids['running']}",
            "job_finished": f"/jobs/{ids['done']}",
            "review": f"/jobs/{ids['review']}/review",
        }
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            for name, url in pages.items():
                for theme in ("light", "dark"):
                    page.emulate_media(color_scheme=theme)
                    page.goto(f"http://127.0.0.1:8765{url}")
                    page.wait_for_timeout(400)
                    target = OUT / f"{name}_{theme}.png"
                    page.screenshot(path=str(target), full_page=True)
                    print(f"{target.name}: {target.stat().st_size:,} bytes")
            browser.close()
        server.should_exit = True
        thread.join(timeout=10)
    finally:
        shutil.rmtree(data_dir, ignore_errors=True)
    print("SCREENSHOTS-OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
