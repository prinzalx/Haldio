"""Tests for the job worker and the FastAPI web UI."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from haldio import __version__
from haldio.config import Config
from haldio.jobs import worker as worker_module
from haldio.jobs.index import JobIndex
from haldio.jobs.worker import Worker
from haldio.pipeline.master import MasterResult
from haldio.pipeline.run import BookResult, ScriptResult
from haldio.pipeline.speak import SpeakResult
from haldio.settings_store import save_override
from haldio.tts.base import ModelGuardError
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
    config.tts.confirm_before_start = False
    index = JobIndex(tmp_path / "data")
    calls: list[str] = []

    def run_fn(
        pdf_path,
        cfg,
        out_dir,
        progress=None,
        stop_after_script=False,
        stop_before_tts=False,
        gate=None,
        language="",
    ):
        calls.append(str(pdf_path))
        if progress:
            progress("editing", 30, "1/2 #ok")
            progress("speaking", 70, "12/40 #ok")
        return _fake_result(out_dir)

    worker = Worker(index, config, run_fn=run_fn, inline=True)
    app = create_app(config, index=index, worker=worker)
    return app, index, calls


def _gate_app(tmp_path, monkeypatch):
    """App with the ready2tts gate on (the shipped default)."""
    config = Config()
    config.paths.data_dir = tmp_path
    index = JobIndex(tmp_path / "data")

    def run_fn(
        pdf_path,
        cfg,
        out_dir,
        progress=None,
        stop_after_script=False,
        stop_before_tts=False,
        gate=None,
        language="",
    ):
        if stop_before_tts:
            return BookResult(
                ScriptResult(out_dir=out_dir, chunks=2),
                SpeakResult(),
                MasterResult(),
                tts_gate=True,
            )
        return _fake_result(out_dir)

    monkeypatch.setattr(
        "haldio.jobs.worker.run_speech",
        lambda folder, cfg, language, **kwargs: _fake_result(folder),
    )
    worker = Worker(index, config, run_fn=run_fn, inline=True)
    app = create_app(config, index=index, worker=worker)
    return app, index


def test_ready2tts_gate_pauses_and_resumes(tmp_path, monkeypatch) -> None:
    app, index = _gate_app(tmp_path, monkeypatch)
    client = TestClient(app)
    location = _upload_pdf(client)
    job = index.list()[0]
    assert job.status == "awaiting_tts"
    assert job.progress == 60
    page = client.get(location)
    assert "Bitte alle anderen lokalen LLM beenden" in page.text
    response = client.post(f"{location}/speak", follow_redirects=False)
    assert response.status_code == 303
    assert index.get(job.id).status == "done"


def test_ready2tts_pool_starts_all(tmp_path, monkeypatch) -> None:
    app, index = _gate_app(tmp_path, monkeypatch)
    client = TestClient(app)
    _upload_pdf(client)
    _upload_pdf(client)
    assert [job.status for job in index.list()] == ["awaiting_tts", "awaiting_tts"]
    response = client.post("/tts-pool/start", follow_redirects=False)
    assert response.status_code == 303
    assert [job.status for job in index.list()] == ["done", "done"]


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


def test_upload_batch_creates_one_job_per_pdf(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    response = client.post(
        "/upload",
        files=[
            ("file", ("a.pdf", b"%PDF-1.4 erste datei", "application/pdf")),
            ("file", ("b.pdf", b"%PDF-1.4 zweite datei", "application/pdf")),
            ("file", ("c.pdf", b"%PDF-1.4 dritte datei", "application/pdf")),
        ],
        data={"language": "de"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"  # the stack is watched in the library
    jobs = index.list()
    assert len(jobs) == 3
    assert {j.file_name for j in jobs} == {"a.pdf", "b.pdf", "c.pdf"}
    assert all(j.language == "de" for j in jobs)
    # the queue serializes the batch; the fake worker runs all three to done
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and not all(j.status == "done" for j in index.list()):
        time.sleep(0.02)
    assert all(j.status == "done" for j in index.list())
    page = client.get("/").text
    assert "a.pdf" in page and "b.pdf" in page and "c.pdf" in page


def test_upload_batch_rejects_when_one_file_is_no_pdf(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    response = client.post(
        "/upload",
        files=[
            ("file", ("a.pdf", b"%PDF-1.4 erste datei", "application/pdf")),
            ("file", ("notes.txt", b"hello", "text/plain")),
        ],
    )
    assert response.status_code == 400


def test_gate_button_offered_only_after_the_ask(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    job = index.create("a.pdf")
    job.status = "waiting_for_user"
    job.message = "LM Studio lädt noch: bubo · ich prüfe alle 5 Sekunden"
    index.update(job)
    page = client.get(f"/jobs/{job.id}").text
    assert 'data-toast="Weiter geht' not in page  # no button during the auto phase
    job.message = "LM Studio lädt noch: bubo · bitte „Erneut prüfen“ drücken"
    index.update(job)
    page = client.get(f"/jobs/{job.id}").text
    assert 'data-toast="Weiter geht' in page
    assert "Erneut prüfen</button>" in page


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
    assert "Gesamt 100 %" in page.text  # badge replaced by one honest bar
    assert "book.mp3" in page.text


def test_job_api_exposes_logs(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    response = client.get(f"/api{location}")
    assert response.status_code == 200
    body = response.json()
    assert "logs" in body
    assert any("Hörtext schreiben: Abschnitt 1/2" in line for line in body["logs"])


def test_job_page_shows_log_tail(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    page = client.get(location)
    assert "Technische Details" in page.text
    assert "Abschnitt 1/2" in page.text


def test_failed_job_offers_resume_and_restart(app_parts, monkeypatch) -> None:
    app, index, _calls = app_parts
    monkeypatch.setattr(
        "haldio.jobs.worker.run_speech",
        lambda folder, cfg, language, **kwargs: _fake_result(folder),
    )
    client = TestClient(app)
    location = _upload_pdf(client)
    job = index.list()[0]
    script = index.jobs_dir / job.id / "04_script" / "script.json"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text('{"chunks": []}', encoding="utf-8")
    job.status = "failed"
    job.error = "stack expects a non-empty TensorList"
    index.update(job)
    page = client.get(location)
    assert "Weiter — Sprachausgabe" in page.text
    assert "Neu starten" in page.text
    response = client.post(f"{location}/speak", follow_redirects=False)
    assert response.status_code == 303
    done = index.get(job.id)
    assert done.status == "done"
    assert done.error == ""


def test_failed_job_without_script_hides_resume(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job = index.list()[0]
    job.status = "failed"
    index.update(job)
    page = client.get(location)
    assert "Weiter — Sprachausgabe" not in page.text
    assert "Neu starten" in page.text


def test_restart_reruns_full_pipeline(app_parts) -> None:
    app, index, calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job = index.list()[0]
    job.status = "failed"
    job.error = "boom"
    index.update(job)
    response = client.post(f"{location}/restart", follow_redirects=False)
    assert response.status_code == 303
    assert len(calls) == 2
    fresh = index.get(job.id)
    assert fresh.status == "done"
    assert fresh.error == ""


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


def test_failure_message_is_short_and_detail_holds_traceback(tmp_path) -> None:
    config = Config()
    config.paths.data_dir = tmp_path
    index = JobIndex(tmp_path / "data")

    def bad_run(pdf_path, cfg, out_dir, progress=None, **kwargs):
        if progress:
            progress("speaking", 70)
        raise RuntimeError("unit abc123: empty audio")

    job = index.create("x.pdf")
    worker = Worker(index, config, run_fn=bad_run, inline=True)
    worker.enqueue(job.id)
    done = index.get(job.id)
    assert done.status == "failed"
    assert done.message == "Umwandeln in Sprache fehlgeschlagen."
    assert "Traceback" in done.error_detail
    assert "empty audio" in done.error


def test_job_voice_from_upload_page_reaches_tts_config(tmp_path) -> None:
    config = Config()
    config.paths.data_dir = tmp_path
    config.tts.speaker = "dylan"
    index = JobIndex(tmp_path / "data")
    seen: dict[str, str] = {}

    def probe_run(pdf_path, cfg, out_dir, progress=None, **kwargs):
        seen["speaker"] = cfg.tts.speaker
        raise RuntimeError("stop here")

    job = index.create("x.pdf")
    job.options["voice"] = "vivian"
    index.update(job)
    Worker(index, config, run_fn=probe_run, inline=True).enqueue(job.id)
    assert seen["speaker"] == "vivian"


def test_worker_cancel_queued_job(tmp_path) -> None:
    config = Config()
    index = JobIndex(tmp_path / "data")
    job = index.create("x.pdf")

    def never_run(pdf_path, cfg, out_dir, progress=None, **kwargs):  # pragma: no cover
        raise AssertionError("must not run")

    worker = Worker(index, config, run_fn=never_run, inline=False)
    worker.cancel(job.id)
    assert index.get(job.id).status == "cancelled"


def _wait_for_status(index: JobIndex, job_id: str, wanted: str, timeout: float = 5.0) -> str:
    import time

    for _ in range(int(timeout / 0.05)):
        try:
            status = index.get(job_id).status
        except ValueError:
            status = ""  # job.json was mid-write when polled
        if status == wanted:
            return status
        time.sleep(0.05)
    try:
        return index.get(job_id).status
    except ValueError:
        return ""


def test_gate_blocks_until_continue(tmp_path, monkeypatch) -> None:
    """Without a possible guard check the gate waits for the manual Weiter."""
    config = Config()
    config.paths.data_dir = tmp_path
    config.tts.backend = "qwencpp"
    index = JobIndex(tmp_path / "data")
    job = index.create("x.pdf")
    monkeypatch.setattr("haldio.jobs.worker.loaded_llm_models", lambda *a, **k: None)

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        gate = kwargs.get("gate")
        if gate:
            gate("LLM stoppen, dann Weiter drücken.")
        return _fake_result(out_dir)

    worker = Worker(index, config, run_fn=run_fn, inline=False)
    worker.start()  # start() re-queues the already-queued job once; do not enqueue again
    assert _wait_for_status(index, job.id, "waiting_for_user") == "waiting_for_user"
    assert "LLM stoppen" in index.get(job.id).message
    assert worker.continue_job(job.id) is True
    assert _wait_for_status(index, job.id, "done") == "done"


def test_gate_continues_without_http_request(tmp_path, monkeypatch) -> None:
    """The worker's own timer frees the gate; no browser request is needed."""
    config = Config()
    config.paths.data_dir = tmp_path
    config.tts.backend = "qwencpp"
    index = JobIndex(tmp_path / "data")
    job = index.create("x.pdf")
    checks = {"n": 0}

    def fake_guard(*_a, **_k):
        checks["n"] += 1
        return ["bubo"] if checks["n"] < 2 else []

    monkeypatch.setattr("haldio.jobs.worker.loaded_llm_models", fake_guard)
    monkeypatch.setattr(worker_module, "_GATE_STEP_S", 0.01)
    ticks = iter(range(0, 10000, 10))
    monkeypatch.setattr(worker_module.time, "monotonic", lambda: float(next(ticks)))

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        gate = kwargs.get("gate")
        if gate:
            gate("LLM stoppen, dann Weiter drücken.")
        return _fake_result(out_dir)

    worker = Worker(index, config, run_fn=run_fn, inline=False)
    worker.start()
    # nobody presses anything and no HTTP request arrives: the timer frees the gate
    assert _wait_for_status(index, job.id, "done", timeout=30) == "done"
    assert checks["n"] == 2  # first check + one re-check, both by the worker


def test_gate_asks_for_the_button_after_300_seconds(tmp_path, monkeypatch) -> None:
    """The 5-minute ask is counted in seconds by the worker thread, not in polls."""
    config = Config()
    config.paths.data_dir = tmp_path
    config.tts.backend = "qwencpp"
    index = JobIndex(tmp_path / "data")
    job = index.create("x.pdf")
    monkeypatch.setattr("haldio.jobs.worker.loaded_llm_models", lambda *a, **k: ["bubo"])
    monkeypatch.setattr(worker_module, "_GATE_STEP_S", 0.01)
    ticks = iter(range(0, 10000, 60))
    monkeypatch.setattr(worker_module.time, "monotonic", lambda: float(next(ticks)))

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        gate = kwargs.get("gate")
        if gate:
            gate("LLM stoppen, dann Weiter drücken.")
        return _fake_result(out_dir)

    worker = Worker(index, config, run_fn=run_fn, inline=False)
    worker.start()
    asked = ""
    for _ in range(200):
        try:
            asked = index.get(job.id).message
        except (ValueError, json.JSONDecodeError):
            asked = ""  # job.json was mid-write when polled
        if "Erneut prüfen" in asked:
            break
        time.sleep(0.02)
    assert "Erneut prüfen" in asked  # 300 fake seconds after the gate opened
    assert worker.continue_job(job.id) is True
    assert _wait_for_status(index, job.id, "done", timeout=30) == "done"


def test_gate_check_impossible_shows_the_button_hint_after_300_seconds(
    tmp_path, monkeypatch
) -> None:
    """When the guard check stops working, the ask text still appears after 300 s."""
    config = Config()
    config.paths.data_dir = tmp_path
    config.tts.backend = "qwencpp"
    index = JobIndex(tmp_path / "data")
    job = index.create("x.pdf")
    seen = {"n": 0}

    def fake_guard(*_a, **_k):
        seen["n"] += 1
        return ["bubo"] if seen["n"] == 1 else None

    monkeypatch.setattr("haldio.jobs.worker.loaded_llm_models", fake_guard)
    monkeypatch.setattr(worker_module, "_GATE_STEP_S", 0.01)
    ticks = iter(range(0, 10000, 60))
    monkeypatch.setattr(worker_module.time, "monotonic", lambda: float(next(ticks)))

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        gate = kwargs.get("gate")
        if gate:
            gate("LLM stoppen, dann Weiter drücken.")
        return _fake_result(out_dir)

    worker = Worker(index, config, run_fn=run_fn, inline=False)
    worker.start()
    asked = ""
    for _ in range(200):
        try:
            asked = index.get(job.id).message
        except (ValueError, json.JSONDecodeError):
            asked = ""  # job.json was mid-write when polled
        if "Erneut prüfen" in asked:
            break
        time.sleep(0.02)
    assert "(Prüfen nicht möglich)" in asked
    assert "Erneut prüfen" in asked
    assert worker.continue_job(job.id) is True
    assert _wait_for_status(index, job.id, "done", timeout=30) == "done"


def test_continue_route_requeues_without_open_gate(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    _upload_pdf(client)
    job = index.list()[0]
    job.status = "waiting_for_user"
    index.update(job)
    response = client.post(f"/jobs/{job.id}/continue", follow_redirects=False)
    assert response.status_code == 303
    assert index.get(job.id).status == "done"


def test_cancel_waiting_for_user(tmp_path) -> None:
    config = Config()
    index = JobIndex(tmp_path / "data")
    job = index.create("x.pdf")
    job.status = "waiting_for_user"
    index.update(job)
    worker = Worker(index, config, run_fn=_fake_result, inline=False)
    worker.cancel(job.id)
    assert index.get(job.id).status == "cancelled"


def test_settings_page_shows_endpoints(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    page = client.get("/settings")
    assert page.status_code == 200
    assert "Einstellungen" in page.text
    assert "Verbindung testen" in page.text


def test_settings_test_tts_mock(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    response = client.post("/settings/test-tts")
    assert response.status_code == 200
    assert "TTS ok" in response.text


def test_settings_test_tts_is_post_only(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    assert client.get("/settings/test-tts").status_code == 405


def test_upload_rejects_bad_magic(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    response = client.post(
        "/upload",
        files={"file": ("doc.pdf", b"plain text not a pdf", "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 400


def test_upload_rejects_too_large(tmp_path) -> None:
    config = Config()
    config.paths.data_dir = tmp_path
    config.server.max_upload_mb = 1
    index = JobIndex(tmp_path / "data")
    worker = Worker(index, config, run_fn=lambda *a, **k: _fake_result(Path(".")), inline=True)
    app = create_app(config, index=index, worker=worker)
    client = TestClient(app)
    response = client.post(
        "/upload",
        files={"file": ("big.pdf", b"%PDF-" + b"x" * (1024 * 1024 + 10), "application/pdf")},
        follow_redirects=False,
    )
    assert response.status_code == 413


def test_csrf_foreign_origin_rejected(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    _upload_pdf(client)
    job_id = index.list()[0].id
    response = client.post(
        f"/jobs/{job_id}/delete",
        headers={"Origin": "http://evil.example"},
        follow_redirects=False,
    )
    assert response.status_code == 403


def test_delete_is_post_only(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    _upload_pdf(client)
    job_id = index.list()[0].id
    assert client.get(f"/jobs/{job_id}/delete").status_code == 405


def test_review_save_keeps_fields_and_rewrites_md(app_parts) -> None:
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
                        "needs_review": False,
                    }
                ],
                "chapter_ids": ["c0001"],
                "doc_meta": {"title": "Buch"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    response = client.post(
        f"/jobs/{job_id}/review", data={"c0b0": "Neuer Text."}, follow_redirects=False
    )
    assert response.status_code == 303
    data = json.loads(script_file.read_text(encoding="utf-8"))
    assert data["chapter_ids"] == ["c0001"]
    assert data["doc_meta"] == {"title": "Buch"}
    assert data["chunks"][0]["blocks"][0]["text"] == "Neuer Text."
    markdown = (script_file.parent / "script.md").read_text(encoding="utf-8")
    assert "Neuer Text." in markdown and "Alter Text." not in markdown


def test_model_guard_blocks_server_start(monkeypatch) -> None:
    from haldio.config import TtsConfig
    from haldio.tts.base import TTSParams
    from haldio.tts.qwencpp import QwenCppBackend

    monkeypatch.setattr("haldio.tts.qwencpp.loaded_llm_models", lambda **kw: ["bubo"])
    backend = QwenCppBackend(TtsConfig(backend="qwencpp"))
    with pytest.raises(Exception) as caught:
        backend.synthesize("Hallo.", "de", TTSParams(voice="dylan"))
    assert type(caught.value).__name__ == "ModelGuardError"


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


# --- correction 4, section 3: page content ---


def test_status_labels_are_german_for_every_status() -> None:
    from haldio.jobs.index import STATUS_VALUES
    from haldio.web.labels import status_label

    for status in STATUS_VALUES:
        data = status_label(status)
        assert data["label"], f"{status} has no label"
        assert data["icon"] and data["cls"], f"{status} has no icon/class"
    assert status_label("done")["label"] == "Fertig"
    assert status_label("failed")["label"] == "Fehlgeschlagen"
    assert status_label("nope")["label"] == "nope"


def test_stepper_state_marks_failed_stage() -> None:
    from haldio.jobs.index import Job
    from haldio.web.labels import stepper_state

    job = Job(id="j", file_name="a.pdf", status="failed", options={"stage": "speaking"})
    states = [row["state"] for row in stepper_state(job)]
    assert states == ["done", "done", "done", "done", "done", "failed", "pending"]


def test_stepper_state_agrees_with_badge_per_status() -> None:
    """Test table: every status has exactly one row set and no 'läuft' while waiting."""
    from haldio.jobs.index import STATUS_VALUES, Job
    from haldio.web.labels import stepper_state

    def states_for(status: str, stage: str = "") -> list[str]:
        job = Job(id="j", file_name="a.pdf", status=status, options={"stage": stage})
        if status == "speaking":
            job.activity = {"stage": "speaking"}
        return [row["state"] for row in stepper_state(job)]

    assert states_for("awaiting_tts") == [
        "done",
        "done",
        "done",
        "done",
        "done",
        "waiting",
        "pending",
    ]
    assert states_for("awaiting_review") == [
        "done",
        "done",
        "done",
        "done",
        "waiting",
        "pending",
        "pending",
    ]
    assert states_for("waiting_for_user") == [
        "done",
        "done",
        "done",
        "done",
        "done",
        "waiting",
        "pending",
    ]
    assert states_for("queued") == [
        "waiting",
        "pending",
        "pending",
        "pending",
        "pending",
        "pending",
        "pending",
    ]
    assert states_for("speaking") == ["done", "done", "done", "done", "done", "current", "pending"]
    assert states_for("done") == ["done"] * 7
    assert states_for("cancelled", "editing") == [
        "done",
        "done",
        "failed",
        "pending",
        "pending",
        "pending",
        "pending",
    ]
    for status in STATUS_VALUES:
        states = states_for(status, "speaking")
        assert len(states) == 7
        if status in ("awaiting_tts", "awaiting_review", "waiting_for_user", "queued"):
            assert "current" not in states  # nothing may claim "läuft" while waiting


def test_library_empty_text_and_job_title(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    assert "Noch keine Jobs. Laden Sie ein PDF hoch." in client.get("/").text
    location = _upload_pdf(client)
    job = index.get(location.rsplit("/", 1)[-1])
    job.title = "Mein Buch"
    index.update(job)
    page = client.get("/")
    assert "Mein Buch" in page.text
    assert "Noch keine Jobs" not in page.text


def test_upload_reads_form_fields(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    response = client.post(
        "/upload",
        files={"file": ("test.pdf", b"%PDF-1.4 fake pdf body", "application/pdf")},
        data={"voice": "dylan", "language": "de", "review": "true"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    job = index.get(response.headers["location"].rsplit("/", 1)[-1])
    assert job.options["voice"] == "dylan"
    assert job.options["language"] == "de"
    assert job.options["review"] is True
    assert job.language == "de"


def test_library_banner_counts_waiting_jobs(tmp_path, monkeypatch) -> None:
    app, index = _gate_app(tmp_path, monkeypatch)
    client = TestClient(app)
    _upload_pdf(client)
    page = client.get("/")
    assert "1 Job warten auf die Sprachausgabe" in page.text
    assert "Alle TTS starten" in page.text


def test_job_page_shows_german_label_and_stepper(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    page = client.get(location)
    assert "Fertig" in page.text
    assert "stepper" in page.text
    assert "Audio fertigstellen" in page.text


def test_job_page_summary_card_from_doc_map(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job_id = location.rsplit("/", 1)[-1]
    doc_map = index.jobs_dir / job_id / "02_plan" / "doc_map.json"
    doc_map.parent.mkdir(parents=True, exist_ok=True)
    doc_map.write_text(
        '{"language": "de", "estimated_audio_seconds": 4200, "main_topics": ["Technik"]}',
        encoding="utf-8",
    )
    page = client.get(location)
    assert "Zusammenfassung" in page.text
    assert "1 h 10 min" in page.text
    assert "Themen" not in page.text  # the topics row was dropped from the card


def test_topbar_marks_the_active_page(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    assert 'aria-current="page"' in client.get("/").text  # logo marks the library
    assert 'aria-current="page"' in client.get("/settings").text
    location = _upload_pdf(client)
    assert "aria-current" not in client.get(location).text  # job page: neither


def test_topbar_has_only_the_logo_link(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    topbar = client.get("/").text.split('<header class="topbar">', 1)[1]
    topbar = topbar.split("</header>", 1)[0]
    assert "Bücherei" not in topbar  # the logo is the only way home
    assert topbar.count('href="/"') == 1  # one logo link
    assert "dev" not in topbar and f"v{__version__}" not in topbar  # no version chip
    assert "Einstellungen" in topbar


def test_version_shows_in_footer_and_settings(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    footer = client.get("/").text.split("</main>", 1)[1]
    assert f"v{__version__}" in footer  # real version, small footer only
    settings = client.get("/settings").text.split("</main>", 1)[0]
    assert f"Version {__version__}" in settings  # from package metadata


_SETTINGS_FORM = {
    "llm.base_url": "http://127.0.0.1:8080/v1",
    "llm.model": "qwen3-test",
    "tts.speaker": "",
    "tts.language": "de",
    "audio.format.mp3": "on",
    "audio.mp3_bitrate_kbps": "128",
    "editor.review_before_tts": "on",
    "tts.confirm_before_start": "on",
    "editor.fallback_to_source": "on",
    "editor.max_retries": "2",
}


def test_settings_save_writes_override_file(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    response = client.post("/settings", data=_SETTINGS_FORM, follow_redirects=False)
    assert response.status_code == 303
    text = (app.state.config.paths.data_dir / "settings.local.yaml").read_text(encoding="utf-8")
    assert "qwen3-test" in text
    assert "speaker" not in text  # the empty field keeps the default speaker
    page = client.get("/settings").text
    assert "qwen3-test" in page  # the effective value is shown after the save
    assert app.state.config.llm.model == "bubo"  # the base config keeps its value


def test_settings_save_rejects_bad_bitrate(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    bad = dict(_SETTINGS_FORM, **{"audio.mp3_bitrate_kbps": "999"})
    page = client.post("/settings", data=bad)
    assert page.status_code == 422
    assert "Bitrate: ganze Zahl von 32 bis 320." in page.text
    assert not (app.state.config.paths.data_dir / "settings.local.yaml").is_file()


def test_settings_reset_removes_override(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    client.post("/settings", data=_SETTINGS_FORM, follow_redirects=False)
    response = client.post("/settings/reset", follow_redirects=False)
    assert response.status_code == 303
    assert not (app.state.config.paths.data_dir / "settings.local.yaml").is_file()
    assert "bubo" in client.get("/settings").text  # defaults are back


def test_settings_llm_card_has_dropdown_and_buttons(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    page = client.get("/settings").text
    assert "Sprachmodell (LLM)" in page  # the card exists
    assert 'select id="f-model"' in page  # model is a dropdown
    assert "Modelle laden" in page
    assert "Verbindung testen" in page
    assert 'id="f-model-free"' in page  # free text stays ready if lms fails


def test_settings_model_list_marks_loaded(app_parts, monkeypatch) -> None:
    app, _index, _calls = app_parts
    monkeypatch.setattr("haldio.web.app.loaded_llm_models", lambda *a, **k: ["bubo"], raising=True)
    monkeypatch.setattr(
        "haldio.llm.client.LlmClient.list_models",
        lambda self: ["bubo", "qwen3"],
        raising=True,
    )
    client = TestClient(app)
    data = client.get("/settings/models").json()
    assert data["ok"] is True
    assert data["models"] == ["bubo", "qwen3"]
    assert data["loaded"] == ["bubo"]
    assert data["current"] == "bubo"  # the configured model


def test_settings_model_list_reports_unreachable(app_parts, monkeypatch) -> None:
    app, _index, _calls = app_parts

    def boom(self):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("haldio.llm.client.LlmClient.list_models", boom, raising=True)
    client = TestClient(app)
    data = client.get("/settings/models").json()
    assert data["ok"] is False
    assert "connection refused" in data["error"]


def test_settings_speaker_card_lists_nine_speakers(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    page = client.get("/settings").text
    assert "Sprecher (TTS)" in page
    assert page.count('name="tts.speaker"') == 9  # nine radio rows
    assert "Hauptsprache" not in page  # names only, no description text
    assert "Dylan" in page
    row = page.split('value="dylan"', 1)[1][:30]
    assert "checked" in row  # the chosen speaker is marked
    assert "Hörprobe erzeugen" in page
    assert page.count("Hörprobe erzeugen") == 1  # one button by the test text
    assert 'id="probe-btn"' in page
    assert ":checked" in page  # button reads the voice selected by radio
    assert "f-probe-text" in page  # and the Testtext field from the hx-vals
    # the js in hx-vals must stay valid JavaScript: attribute in double
    # quotes, JS strings in single quotes (a browser click test found this)
    assert 'hx-vals="js:' in page
    assert "hx-vals='js:" not in page
    assert "vorher das LLM entladen" in page  # guard warning text
    assert 'id="f-lang"' in page  # Sprache stays Automatisch/Deutsch/Englisch


def test_settings_sample_endpoint_with_mock(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    response = client.post("/settings/sample", data={"voice": "dylan"})
    assert response.status_code == 200
    assert "Hörprobe fertig: Dylan" in response.text
    data_dir = app.state.config.paths.data_dir
    assert (data_dir / "samples" / "dylan.wav").is_file()
    assert "<audio" in response.text
    page = client.get("/settings").text
    assert "/samples/dylan.wav" in page  # existing sample plays first, no button
    assert client.get("/samples/dylan.wav").status_code == 200
    assert client.get("/samples/ohne.wav").status_code == 404


def test_settings_sample_guard_stops(app_parts, monkeypatch) -> None:
    app, _index, _calls = app_parts

    def boom(*a, **k):
        raise ModelGuardError("LM Studio lädt noch")

    monkeypatch.setattr("haldio.tts.create_backend", boom, raising=True)
    client = TestClient(app)
    page = client.post("/settings/sample", data={"voice": "vivian"}).text
    assert "Gestoppt" in page and "result-warn" in page


class _ProbeBackend:
    """Records the text and language of each synthesize call."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def synthesize(self, text: str, language: str, params: object) -> object:
        from haldio.tts.base import AudioResult

        self.calls.append((text, language))
        return AudioResult(data=b"RIFFfake", duration_seconds=0.5)

    def close(self) -> None:
        pass


def test_settings_sample_uses_the_test_text(app_parts, monkeypatch) -> None:
    app, _index, _calls = app_parts
    backend = _ProbeBackend()
    monkeypatch.setattr("haldio.tts.create_backend", lambda *a, **k: backend, raising=True)
    client = TestClient(app)
    response = client.post(
        "/settings/sample",
        data={"voice": "dylan", "text": "  Sondertext   zum Ausprobieren ", "language": "en"},
    )
    assert response.status_code == 200
    assert backend.calls == [("Sondertext zum Ausprobieren", "en")]


def test_settings_sample_language_falls_back_to_default_text(app_parts, monkeypatch) -> None:
    app, _index, _calls = app_parts
    backend = _ProbeBackend()
    monkeypatch.setattr("haldio.tts.create_backend", lambda *a, **k: backend, raising=True)
    client = TestClient(app)
    client.post("/settings/sample", data={"voice": "dylan", "language": "en"})
    client.post("/settings/sample", data={"voice": "vivian", "language": "auto"})
    assert backend.calls[0][0].startswith("Hello")  # English default for language=en
    assert backend.calls[1] == ("Guten Tag. Dies ist eine Hörprobe.", "auto")


def test_settings_test_tts_guard_stops(app_parts, monkeypatch) -> None:
    app, _index, _calls = app_parts

    def boom(*a, **k):
        raise ModelGuardError("LM Studio lädt noch")

    monkeypatch.setattr("haldio.tts.create_backend", boom, raising=True)
    client = TestClient(app)
    page = client.post("/settings/test-tts").text
    assert "Gestoppt" in page and "result-warn" in page


def test_settings_quality_lists_existing_models_only(app_parts, monkeypatch) -> None:
    app, _index, _calls = app_parts
    models = app.state.config.paths.data_dir / "modelle"
    models.mkdir()
    q8 = models / "qwen-talker-1.7b-customvoice-Q8_0.gguf"
    q4 = models / "qwen-talker-1.7b-customvoice-Q4_K_M.gguf"
    gone = models / "qwen-talker-1.7b-customvoice-Q6_K.gguf"  # listed, not on disk
    q8.write_bytes(b"x")
    q4.write_bytes(b"x")
    monkeypatch.setattr(app.state.config.tts, "qwencpp_model", str(q8), raising=True)
    monkeypatch.setattr(
        app.state.config.tts, "qwencpp_codec", str(gone), raising=True
    )  # codec is not listed; only talker files are
    client = TestClient(app)
    page = client.get("/settings").text
    assert "Standard (Q8)" in page
    assert "Kleiner und schneller (Q4)" in page
    assert "Q6" not in page  # a file that does not exist is not offered
    form = dict(_SETTINGS_FORM, **{"tts.qwencpp_model": str(q4)})
    response = client.post("/settings", data=form, follow_redirects=False)
    assert response.status_code == 303
    text = (app.state.config.paths.data_dir / "settings.local.yaml").read_text(encoding="utf-8")
    assert "Q4_K_M" in text
    bad = dict(_SETTINGS_FORM, **{"tts.qwencpp_model": str(gone)})
    page = client.post("/settings", data=bad)
    assert page.status_code == 422
    assert "Modell-Datei nicht gefunden." in page.text


def test_settings_advanced_card_holds_rare_settings(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    page = client.get("/settings").text
    assert "Erweitert" in page and "<details" in page  # collapsed card
    assert "Neustart nötig" in page
    assert 'name="server.host"' in page and 'name="server.port"' in page
    assert "readonly" not in page  # server fields are editable now
    assert "API-Schlüssel" in page and "lm-studio" not in page  # key never shown
    for field in (
        "llm.timeout_s",
        "tts.max_chars_per_unit",
        "llm.temperature",
        "tts.qwencpp_port",
        "tts.qwencpp_startup_timeout",
    ):
        assert f'name="{field}"' in page
    assert "Pause nach Absatz" in page and "Pause nach Kapitel" in page


def test_settings_server_host_port_save_and_validate(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    form = dict(_SETTINGS_FORM, **{"server.host": "0.0.0.0", "server.port": "9000"})
    response = client.post("/settings", data=form, follow_redirects=False)
    assert response.status_code == 303
    text = (app.state.config.paths.data_dir / "settings.local.yaml").read_text(encoding="utf-8")
    assert "host: 0.0.0.0" in text and "port: 9000" in text
    page = client.get("/settings").text
    assert 'value="0.0.0.0"' in page  # stored value shows up in the form
    bad = dict(_SETTINGS_FORM, **{"server.port": "abc"})
    page = client.post("/settings", data=bad)
    assert page.status_code == 422
    assert "Port: ganze Zahl von 1 bis 65535." in page.text


def test_settings_api_key_status_words(app_parts, monkeypatch) -> None:
    app, _index, _calls = app_parts
    monkeypatch.setattr(app.state.config.llm, "api_key", "", raising=True)
    page = TestClient(app).get("/settings").text
    assert "API-Schlüssel: nicht gesetzt" in page


def test_settings_save_rare_settings(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    form = dict(
        _SETTINGS_FORM,
        **{
            "audio.pause_ms.paragraph": "0,5",
            "audio.pause_ms.heading": "0,9",
            "audio.pause_ms.chapter": "2",
            "llm.temperature": "0,7",
            "llm.timeout_s": "600",
            "tts.max_chars_per_unit": "500",
            "tts.qwencpp_port": "8111",
            "tts.qwencpp_startup_timeout": "300",
        },
    )
    response = client.post("/settings", data=form, follow_redirects=False)
    assert response.status_code == 303
    text = (app.state.config.paths.data_dir / "settings.local.yaml").read_text(encoding="utf-8")
    assert "paragraph: 500" in text  # seconds became milliseconds on disk
    assert "temperature: 0.7" in text
    page = client.get("/settings").text
    assert 'value="0,7"' in page  # effective value shown back in comma form


def test_settings_pause_rejects_bad_value(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    form = dict(
        _SETTINGS_FORM,
        **{
            "audio.pause_ms.paragraph": "abc",
            "audio.pause_ms.heading": "0,9",
            "audio.pause_ms.chapter": "1,5",
        },
    )
    page = client.post("/settings", data=form)
    assert page.status_code == 422
    assert "Pause: Zahl zwischen 0 und 30 Sekunden." in page.text
    assert not (app.state.config.paths.data_dir / "settings.local.yaml").is_file()


def test_settings_rare_field_error_opens_advanced(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    form = dict(_SETTINGS_FORM, **{"llm.temperature": "5"})
    page = client.post("/settings", data=form)
    assert page.status_code == 422
    assert "Temperatur: Zahl zwischen 0 und 2." in page.text
    assert '<details class="card open">' in page.text  # error stays visible


def test_settings_no_paths_in_rendered_html(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    page = client.get("/settings").text
    visible = re.sub(r'(value|src|href|action)="[^"]*"', "x", page)
    assert not re.search(r"[A-Za-z]:[\\/]", visible)  # no drive letters
    assert "../" not in visible  # no folder walks
    assert "settings.local.yaml" not in visible  # no file names either
    assert ">Dokumentation</a>" in page  # the paths live in the docs


def test_documentation_page_served(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    doc = client.get("/dokumentation")
    assert doc.status_code == 200
    text = doc.text
    assert "settings.local.yaml" in text  # override file explained
    assert "qwen-talker" in text  # model file paths explained
    assert "Neustart nötig" in text


def test_settings_test_llm_unreachable_shows_error(app_parts, monkeypatch) -> None:
    app, _index, _calls = app_parts

    def boom(self):
        raise RuntimeError("connection refused")

    monkeypatch.setattr("haldio.llm.client.LlmClient.list_models", boom, raising=True)
    client = TestClient(app)
    page = client.get("/settings/test-llm").text
    assert "result-error" in page and "Fehler" in page


def test_settings_test_llm_reports_count_and_missing(app_parts, monkeypatch) -> None:
    app, _index, _calls = app_parts
    monkeypatch.setattr(
        "haldio.llm.client.LlmClient.list_models",
        lambda self: ["bubo", "qwen3"],
        raising=True,
    )
    client = TestClient(app)
    page = client.get("/settings/test-llm").text
    assert "result-ok" in page and "2 Modelle" in page and "gewähltes Modell vorhanden" in page


def test_settings_test_llm_flags_a_missing_model(app_parts, monkeypatch) -> None:
    app, _index, _calls = app_parts
    monkeypatch.setattr(
        "haldio.llm.client.LlmClient.list_models", lambda self: ["qwen3"], raising=True
    )
    client = TestClient(app)
    page = client.get("/settings/test-llm").text
    assert "result-warn" in page and "bubo fehlt" in page


def test_job_start_uses_override(tmp_path) -> None:
    config = Config()
    config.paths.data_dir = tmp_path
    index = JobIndex(tmp_path / "data")
    seen: dict[str, str] = {}

    def run_fn(pdf_path, cfg, out_dir, **kwargs):
        seen["model"] = cfg.llm.model
        return _fake_result(out_dir)

    save_override(tmp_path, {"llm": {"model": "überschrieben"}})
    worker = Worker(index, config, run_fn=run_fn, inline=True)
    app = create_app(config, index=index, worker=worker)
    client = TestClient(app)
    _upload_pdf(client)
    assert seen["model"] == "überschrieben"


def test_settings_page_shows_form_and_server(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    page = client.get("/settings")
    assert 'name="llm.model"' in page.text  # fields are editable now
    assert "8505" in page.text  # read-only server line
    assert "Auf Standard zurücksetzen" in page.text


def test_calm_look_polish_in_stylesheet() -> None:
    css = (
        Path(__file__).resolve().parents[1] / "src" / "haldio" / "web" / "static" / "style.css"
    ).read_text(encoding="utf-8")
    assert "box-shadow" in css  # cards lifted from the page
    assert "accent-color" in css  # one honest progress colour
    assert "button:not(:disabled):hover" in css  # only live buttons answer the pointer
    assert "text-decoration: none" in css  # calm links, underline on hover only


def test_section6_spacing_and_type_scale() -> None:
    css = (
        Path(__file__).resolve().parents[1] / "src" / "haldio" / "web" / "static" / "style.css"
    ).read_text(encoding="utf-8")
    for step, px in zip(range(1, 7), ("4px", "8px", "12px", "16px", "24px", "32px"), strict=True):
        assert f"--sp-{step}: {px};" in css  # one spacing scale for all gaps
    assert "h1 { font-size: 22px;" in css  # page title
    assert "h2 { font-size: 16px;" in css  # section titles
    assert ".small, .meta { font-size: 14px; }" in css  # meta text
    assert "margin: var(--sp-3) auto" in css  # layout uses the scale, not ad-hoc px
    media = css.split("@media (max-width: 640px)", 1)[1]
    assert "ol.stepper { flex-direction: column;" in media  # stepper stacks on phones


def test_section6_job_page_order(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job_id = location.rsplit("/", 1)[-1]
    job_dir = index.jobs_dir / job_id
    (job_dir / "02_plan").mkdir(parents=True, exist_ok=True)
    (job_dir / "02_plan" / "doc_map.json").write_text(
        '{"summary": "Test.", "main_topics": ["A"]}', encoding="utf-8"
    )
    (job_dir / "04_script").mkdir(parents=True, exist_ok=True)
    (job_dir / "04_script" / "script.json").write_text('{"chunks": []}', encoding="utf-8")
    page = client.get(location).text
    positions = [
        page.index("<h1>"),
        page.index('id="job-status"'),
        page.index("summary-card"),
        page.index("Skript prüfen (optional)"),
        page.index("Technische Details"),
        page.index("card-actions"),
    ]
    assert positions == sorted(positions)  # header, status, summary, hints, log, actions


def test_delete_button_hidden_while_running(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job_id = location.rsplit("/", 1)[-1]
    assert "🗑 Löschen" in client.get(location).text  # finished: delete offered
    job = index.get(job_id)
    job.status = "speaking"
    index.update(job)
    page = client.get(location)
    assert "🗑 Löschen" not in page.text  # running: no delete in the way
    assert "Abbrechen" in page.text


def test_summary_card_shows_placeholders_while_building(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job_id = location.rsplit("/", 1)[-1]
    doc_map = index.jobs_dir / job_id / "02_plan" / "doc_map.json"
    doc_map.parent.mkdir(parents=True, exist_ok=True)
    doc_map.write_text('{"language": "de"}', encoding="utf-8")
    page = client.get(location)
    assert page.text.count("Wird erstellt …") == 1  # summary only (topics row dropped)
    assert "Geschätzte Länge" not in page.text


def test_result_card_lists_only_existing_files(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job_id = location.rsplit("/", 1)[-1]
    page = client.get(location)
    assert "<audio controls" in page.text
    assert ">MP3<" in page.text
    assert ">OGG<" not in page.text  # only book.mp3 was written by the fake
    ogg = index.jobs_dir / job_id / "06_master" / "book.ogg"
    ogg.write_bytes(b"OggS")
    assert ">OGG<" in client.get(location).text


def test_download_name_uses_job_title(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job_id = location.rsplit("/", 1)[-1]
    job = index.get(job_id)
    job.title = "Mein Buch"
    index.update(job)
    response = client.get(f"{location}/download/book.mp3")
    assert "Mein_Buch.mp3" in response.headers["content-disposition"]


def test_review_chunk_save_swaps_partial(app_parts) -> None:
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
                        "warnings": [{"type": "unclear_source", "detail": " Absatz 2."}],
                        "needs_review": False,
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    response = client.post(f"/jobs/{job_id}/review/chunk", data={"ci": "0", "c0b0": "Neuer Text."})
    assert response.status_code == 200
    assert "Gespeichert" in response.text
    assert "Quelle schwer lesbar: Absatz 2." in response.text
    saved = json.loads(script_file.read_text(encoding="utf-8"))
    assert saved["chunks"][0]["blocks"][0]["text"] == "Neuer Text."
    markdown = (script_file.parent / "script.md").read_text(encoding="utf-8")
    assert "Neuer Text." in markdown


def _review_setup(app_parts, chunks, in_json=None) -> str:
    """Write a script.json (and one chunk input file) for the review tests."""
    import json

    _app, index, _calls = app_parts
    client = TestClient(_app)
    location = _upload_pdf(client)
    job_id = location.rsplit("/", 1)[-1]
    folder = index.jobs_dir / job_id
    (folder / "04_script").mkdir(parents=True, exist_ok=True)
    (folder / "04_script" / "script.json").write_text(
        json.dumps({"chunks": chunks}, ensure_ascii=False), encoding="utf-8"
    )
    if in_json is not None:
        target = folder / "03_edit" / "chunks"
        target.mkdir(parents=True, exist_ok=True)
        for name, payload in in_json.items():
            (target / name).write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return job_id


def test_review_empty_section_has_input_and_buttons(app_parts) -> None:
    _app, _index, _calls = app_parts
    client = TestClient(_app)
    job_id = _review_setup(
        app_parts,
        [{"chunk_id": "c0001", "blocks": [], "warnings": [], "needs_review": False}],
        {
            "c0001.in.json": {
                "chapter_path": "Erstes Kapitel > Anfänge",
                "page_span": [17, 18],
                "blocks": [{"type": "paragraph", "text": "Ursprünglicher Text."}],
            }
        },
    )
    page = client.get(f"/jobs/{job_id}/review")
    assert page.status_code == 200
    assert "Für diesen Abschnitt gibt es keinen Hörtext." in page.text
    assert "Original übernehmen" in page.text
    assert 'name="c0b0"' in page.text
    assert "Seite 17" in page.text
    assert "Erstes Kapitel &gt; Anfänge" in page.text


def test_review_original_shows_tables_and_lists(app_parts) -> None:
    """Table cells and list items must be visible in the Original column."""
    _app, _index, _calls = app_parts
    client = TestClient(_app)
    job_id = _review_setup(
        app_parts,
        [
            {
                "chunk_id": "c0001",
                "blocks": [{"kind": "paragraph", "text": "Hörtext."}],
                "warnings": [],
                "needs_review": False,
            }
        ],
        {
            "c0001.in.json": {
                "blocks": [
                    {"type": "heading", "text": "Kapitel", "level": 1},
                    {
                        "type": "table",
                        "text": " ",
                        "cells": [["Einleitung", "4"], ["Kontext", "5"]],
                    },
                    {
                        "type": "list",
                        "text": "",
                        "list_items": [{"text": "erster Punkt", "level": 0}],
                    },
                ]
            }
        },
    )
    page = client.get(f"/jobs/{job_id}/review")
    assert page.status_code == 200
    assert "Einleitung" in page.text and "Kontext" in page.text  # table content
    assert "erster Punkt" in page.text  # list content


def test_review_use_original_copies_text(app_parts) -> None:
    import json

    _app, index, _calls = app_parts
    client = TestClient(_app)
    job_id = _review_setup(
        app_parts,
        [{"chunk_id": "c0001", "blocks": [], "warnings": [], "needs_review": False}],
        {"c0001.in.json": {"blocks": [{"type": "paragraph", "text": "Ursprünglicher Text."}]}},
    )
    response = client.post(f"/jobs/{job_id}/review/use_original", data={"ci": "0"})
    assert response.status_code == 200
    assert "Ursprünglicher Text." in response.text
    script_file = index.jobs_dir / job_id / "04_script" / "script.json"
    saved = json.loads(script_file.read_text(encoding="utf-8"))
    assert saved["chunks"][0]["blocks"][0]["text"] == "Ursprünglicher Text."


def test_review_use_original_includes_table_cells(app_parts) -> None:
    """Copying the original of a table chunk takes the cell content, not the blank."""
    import json

    _app, index, _calls = app_parts
    client = TestClient(_app)
    job_id = _review_setup(
        app_parts,
        [{"chunk_id": "c0001", "blocks": [], "warnings": [], "needs_review": False}],
        {
            "c0001.in.json": {
                "blocks": [
                    {"type": "table", "text": " ", "cells": [["Einleitung", "4"], ["Kontext", "5"]]}
                ]
            }
        },
    )
    response = client.post(f"/jobs/{job_id}/review/use_original", data={"ci": "0"})
    assert response.status_code == 200
    saved = json.loads(
        (index.jobs_dir / job_id / "04_script" / "script.json").read_text(encoding="utf-8")
    )
    assert saved["chunks"][0]["blocks"][0]["text"] == "Einleitung 4; Kontext 5"


def test_review_counter_and_german_reasons(app_parts) -> None:
    _app, _index, _calls = app_parts
    client = TestClient(_app)
    job_id = _review_setup(
        app_parts,
        [
            {
                "chunk_id": "c0001",
                "blocks": [{"kind": "paragraph", "text": "A."}],
                "warnings": ["unclear_source"],
                "needs_review": False,
            },
            {
                "chunk_id": "c0002",
                "blocks": [{"kind": "paragraph", "text": "B."}],
                "warnings": [],
                "needs_review": False,
            },
        ],
    )
    page = client.get(f"/jobs/{job_id}/review")
    assert "1 von 2 Abschnitten mit Hinweis" in page.text
    assert "Quelle schwer lesbar" in page.text
    assert "unclear_source" not in page.text


def test_worker_reports_units_and_resume_language(tmp_path) -> None:
    config = Config()
    config.paths.data_dir = tmp_path
    index = JobIndex(tmp_path / "data")
    job = index.create("x.pdf", options={"language": "de"})

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        if progress:
            progress("speaking", 66, "12/61 #ok")
            seen["detail"] = index.get(job.id).activity.get("detail", "")
        return _fake_result(out_dir)

    seen: dict[str, str] = {}
    worker = Worker(index, config, run_fn=run_fn, inline=True)
    worker.enqueue(job.id)
    done = index.get(job.id)
    assert seen["detail"] == "Einheit 12 von 61"  # no ETA yet: fewer than 5 items
    assert done.options["stage"] == "speaking"
    assert any("Einheit 12/61" in line for line in done.logs)


def test_theme_switch_and_toast_present(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    page = client.get("/")
    assert 'id="theme-switch"' in page.text
    assert 'aria-live="polite"' in page.text
    assert "haldio-theme" in page.text


def test_polling_excludes_logtail(app_parts) -> None:
    """The 2 s poll swaps only the status core; the log details stay in the page."""
    app, index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job = index.get(location.rsplit("/", 1)[-1])
    assert job.logs
    partial = client.get(f"{location}/status").text
    assert "Protokoll" not in partial
    assert "Protokoll" in client.get(location).text


@pytest.mark.parametrize("status", ["awaiting_tts", "awaiting_review", "waiting_for_user"])
def test_polling_runs_in_every_waiting_state(app_parts, status) -> None:
    """Correction 5: the page must refresh while a job waits, not only while it runs."""
    app, index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job = index.get(location.rsplit("/", 1)[-1])
    job.status = status
    index.update(job)
    partial = client.get(f"{location}/status").text
    assert "every 2s" in partial


def test_polling_stops_in_final_states(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job = index.get(location.rsplit("/", 1)[-1])
    assert job.status == "done"
    assert "every 2s" not in client.get(f"{location}/status").text


def test_log_endpoint_returns_new_lines_only(app_parts) -> None:
    app, index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    job_id = location.rsplit("/", 1)[-1]
    full = client.get(f"/jobs/{job_id}/log")
    assert full.status_code == 200
    body = full.json()
    assert body["count"] == len(body["lines"]) > 1
    tail = client.get(f"/jobs/{job_id}/log?after={body['count'] - 1}")
    assert len(tail.json()["lines"]) == 1
    assert tail.json()["count"] == body["count"]


def test_log_download_is_plain_text(app_parts) -> None:
    app, _index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    response = client.get(f"{location}/log.txt")
    assert response.status_code == 200
    assert "Hörtext schreiben: gestartet" in response.text


def test_status_block_renders_activity_detail(app_parts) -> None:
    """Stepper, badge and status text all read the ONE activity record."""
    app, _index, _calls = app_parts
    client = TestClient(app)
    location = _upload_pdf(client)
    page = client.get(location)
    assert "zuletzt aktiv vor" in page.text
    assert "Technische Details" in page.text
