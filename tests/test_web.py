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
    assert done.message == "Vorlesen fehlgeschlagen."
    assert "Traceback" in done.error_detail
    assert "empty audio" in done.error


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


def test_gate_continues_by_itself_when_model_unloads(tmp_path, monkeypatch) -> None:
    """Fake guard: loaded -> unloaded; the flow re-checks and continues alone."""
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

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        gate = kwargs.get("gate")
        if gate:
            gate("LLM stoppen, dann Weiter drücken.")
        return _fake_result(out_dir)

    worker = Worker(index, config, run_fn=run_fn, inline=False)
    worker.start()
    # nobody presses anything: the re-check after 5 s frees the gate
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
    assert "Test LM Studio" in page.text


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
        "done", "done", "done", "done", "done", "waiting", "pending"]
    assert states_for("awaiting_review") == [
        "done", "done", "done", "done", "waiting", "pending", "pending"]
    assert states_for("waiting_for_user") == [
        "done", "done", "done", "done", "done", "waiting", "pending"]
    assert states_for("queued") == [
        "waiting", "pending", "pending", "pending", "pending", "pending", "pending"]
    assert states_for("speaking") == [
        "done", "done", "done", "done", "done", "current", "pending"]
    assert states_for("done") == ["done"] * 7
    assert states_for("cancelled", "editing") == [
        "done", "done", "failed", "pending", "pending", "pending", "pending"]
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
    assert "Technik" in page.text


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


def test_review_counter_and_german_reasons(app_parts) -> None:
    _app, _index, _calls = app_parts
    client = TestClient(_app)
    job_id = _review_setup(
        app_parts,
        [
            {"chunk_id": "c0001", "blocks": [{"kind": "paragraph", "text": "A."}],
             "warnings": ["unclear_source"], "needs_review": False},
            {"chunk_id": "c0002", "blocks": [{"kind": "paragraph", "text": "B."}],
             "warnings": [], "needs_review": False},
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
