"""Tests for the job worker and the FastAPI web UI."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from haldio.config import Config
from haldio.jobs.index import JobIndex
from haldio.jobs.worker import Worker
from haldio.pipeline.master import MasterResult
from haldio.pipeline.run import BookResult, ScriptResult
from haldio.pipeline.speak import SpeakResult
from haldio.web.app import create_app


def _fake_result(out_dir: Path) -> BookResult:
    master_file = out_dir / "06_master" / "book.mp3"
    master_file.parent.mkdir(parents=True, exist_ok=True)
    master_file.write_bytes(b"ID3fake")
    return BookResult(
        script=ScriptResult(out_dir=out_dir, chunks=2),
        speak=SpeakResult(units=[{"file": "x"}], synthesized=3, total_seconds=42.0),
        master=MasterResult(files=[master_file]),
    )


@pytest.fixture()
def app_parts(tmp_path):
    config = Config()
    config.paths.data_dir = tmp_path
    index = JobIndex(tmp_path / "data")
    calls: list[str] = []

    def run_fn(pdf_path, cfg, out_dir, progress=None, stop_after_script=False):
        calls.append(str(pdf_path))
        if progress:
            progress("editing", 30)
            progress("speaking", 70)
        return _fake_result(out_dir)

    worker = Worker(index, config, run_fn=run_fn, inline=True)
    app = create_app(config, index=index, worker=worker)
    return app, index, calls


def _upload_pdf(client: TestClient) -> str:
    response = client.post(
        "/upload",
        files={"file": ("test.pdf", b"%PDF-1.4 fake pdf body", "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 303
    return response.headers["location"]


def test_library_lists_empty(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    page = client.get("/")
    assert page.status_code == 200
    assert "Bücherei" in page.text


def test_upload_runs_job_and_shows_done(app_parts) -> None:
    app, index, calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    assert len(calls) == 1
    jobs = index.list()
    assert jobs[0].status == "done"
    assert jobs[0].audio_seconds == 42
    page = client.get(location)
    assert page.status_code == 200
    assert "badge-done" in page.text
    assert "book.mp3" in page.text


def test_upload_rejects_non_pdf(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    response = client.post("/upload", files={"file": ("notes.txt", b"hello", "text/plain")})
    assert response.status_code == 400


def test_download_serves_master_file(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    response = client.get(f"{location}/download/book.mp3")
    assert response.status_code == 200
    assert response.content == b"ID3fake"
    missing = client.get(f"{location}/download/script.md")
    assert missing.status_code == 404


def test_delete_removes_job(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job_id = location.rsplit("/", 1)[-1]
    response = client.post(f"/jobs/{job_id}/delete", follow_redirects=False)
    assert response.status_code == 303
    assert index.list() == []


def test_unknown_job_is_404(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    assert client.get("/jobs/nope").status_code == 404


def test_worker_cancel_queued_job(tmp_path) -> None:
    config = Config()
    index = JobIndex(tmp_path / "data")
    job = index.create("x.pdf")

    def never_run(pdf_path, cfg, out_dir, progress=None, **kwargs):  # pragma: no cover
        raise AssertionError("must not run")

    worker = Worker(index, config, run_fn=never_run, inline=False)
    worker.cancel(job.id)
    assert index.get(job.id).status == "cancelled"


def test_settings_page_shows_endpoints(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    page = client.get("/settings")
    assert page.status_code == 200
    assert "Einstellungen" in page.text
    assert "Test LM Studio" in page.text


def test_settings_test_tts_mock(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    response = client.get("/settings/test-tts")
    assert response.status_code == 200
    assert "TTS ok" in response.text


def test_review_page_and_edit(app_parts, tmp_path) -> None:
    import json

    app, index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job_id = location.rsplit("/", 1)[-1]
    script_file = index.jobs_dir / job_id / "04_script" / "script.json"
    script_file.parent.mkdir(parents=True, exist_ok=True)
    script_file.write_text(
        json.dumps(
            {
                "chunks": [
                    {
                        "chunk_id": "c0001",
                        "blocks": [{"kind": "paragraph", "text": "Alter Text."}],
                        "warnings": [],
                        "needs_review": True,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    page = client.get(f"/jobs/{job_id}/review")
    assert page.status_code == 200
    assert "Alter Text." in page.text
    response = client.post(
        f"/jobs/{job_id}/review", data={"c0b0": "Neuer Text."}, follow_redirects=False
    )
    assert response.status_code == 303
    saved = json.loads(script_file.read_text(encoding="utf-8"))
    assert saved["chunks"][0]["blocks"][0]["text"] == "Neuer Text."


def test_speak_now_sets_resume_option(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job_id = location.rsplit("/", 1)[-1]
    response = client.post(f"/jobs/{job_id}/speak", follow_redirects=False)
    # the inline worker re-ran immediately (fake pipeline); the option was set first
    assert response.status_code == 303
    job = index.get(job_id)
    assert job.options.get("resume_from") == "speaking"
