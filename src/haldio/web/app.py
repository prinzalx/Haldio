"""FastAPI web UI (German): library page, job page, downloads."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from haldio import __version__
from haldio.config import Config
from haldio.jobs.index import Job, JobIndex
from haldio.jobs.worker import Worker
from haldio.pipeline.assemble import render_script_md
from haldio.tts.base import ModelGuardError
from haldio.web.labels import stage_rows, status_label, warning_text

WEB_DIR = Path(__file__).parent
MAX_UPLOAD_BYTES_FALLBACK = 100 * 1024 * 1024


def create_app(
    config: Config, index: JobIndex | None = None, worker: Worker | None = None
) -> FastAPI:
    """Build the web application. Tests pass an inline worker."""
    app = FastAPI(title="Haldio", version=__version__)
    app.state.config = config
    app.state.index = index or JobIndex(config.paths.data_dir)
    app.state.worker = worker or Worker(app.state.index, config)
    app.state.worker.start()
    templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
    templates.env.filters["seconds"] = _format_seconds
    templates.env.filters["status_label"] = status_label
    templates.env.filters["warning_text"] = warning_text
    templates.env.filters["date"] = _format_date
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    @app.middleware("http")
    async def csrf_origin(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        """Reject POSTs from a foreign origin (other web pages can target localhost)."""
        if request.method == "POST":
            origin = request.headers.get("origin") or request.headers.get("referer") or ""
            host = origin.split("://", 1)[1].split("/", 1)[0] if "://" in origin else ""
            if host and host != request.headers.get("host"):
                return HTMLResponse("CSRF-Schutz: fremde Quelle.", status_code=403)
        return await call_next(request)

    @app.get("/", response_class=HTMLResponse)
    def library(request: Request) -> HTMLResponse:
        jobs = app.state.index.list()
        return templates.TemplateResponse(
            request,
            "library.html",
            {
                "jobs": jobs,
                "version": __version__,
                "voices": _available_voices(config),
                "selected_voice": config.tts.speaker or "dylan",
            },
        )

    @app.post("/upload")
    async def upload(
        file: UploadFile = File(...),  # noqa: B008 - FastAPI pattern
        voice: str = Form("dylan"),
        language: str = Form("auto"),
        review: bool = Form(False),
    ) -> RedirectResponse:
        name = file.filename or "upload.pdf"
        if not name.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Nur PDF-Dateien sind erlaubt.")
        limit = config.server.max_upload_mb * 1024 * 1024
        data = await _read_limited(file, limit)
        if not data.startswith(b"%PDF-"):
            raise HTTPException(status_code=400, detail="Datei ist kein PDF (Magic Bytes).")
        options = {"voice": voice, "language": language, "review": review}
        job = app.state.index.create(name, options=options)
        if language in ("de", "en"):
            job.language = language
            app.state.index.update(job)
        folder = app.state.index.jobs_dir / job.id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "source.pdf").write_bytes(data)
        app.state.worker.enqueue(job.id)
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(request: Request, job_id: str) -> HTMLResponse:
        job = _require_job(app.state.index, job_id)
        return templates.TemplateResponse(
            request, "job.html", _job_context(app.state.index, job_id, job)
        )

    @app.get("/api/jobs/{job_id}")
    def job_api(job_id: str) -> dict[str, Any]:
        return _require_job(app.state.index, job_id).to_dict()

    @app.get("/jobs/{job_id}/status", response_class=HTMLResponse)
    def job_status(request: Request, job_id: str) -> HTMLResponse:
        job = _require_job(app.state.index, job_id)
        return templates.TemplateResponse(
            request, "partials/job_status.html", _job_context(app.state.index, job_id, job)
        )

    @app.get("/jobs/{job_id}/log")
    def job_log_tail(job_id: str, after: int = 0) -> dict[str, Any]:
        """New log lines since index <after> (polled while the box is open)."""
        logs = _require_job(app.state.index, job_id).logs
        return {"count": len(logs), "lines": logs[after:]}

    @app.get("/jobs/{job_id}/log.txt", response_class=PlainTextResponse)
    def job_log_file(job_id: str) -> PlainTextResponse:
        job = _require_job(app.state.index, job_id)
        path = app.state.index.jobs_dir / job_id / "logs" / "job.log"
        if path.is_file():
            return PlainTextResponse(path.read_text(encoding="utf-8"))
        return PlainTextResponse("\n".join(job.logs) + ("\n" if job.logs else ""))

    @app.get("/jobs/{job_id}/download/{file_name}")
    def download(job_id: str, file_name: str) -> FileResponse:
        job = _require_job(app.state.index, job_id)
        if file_name not in _DOWNLOADABLE:
            raise HTTPException(status_code=404, detail="Unbekannte Datei.")
        candidates = [
            app.state.index.jobs_dir / job_id / "06_master" / file_name,
            app.state.index.jobs_dir / job_id / "04_script" / file_name,
            app.state.index.jobs_dir / job_id / file_name,
        ]
        for path in candidates:
            if path.is_file():
                return FileResponse(path, filename=_download_name(job, file_name))
        raise HTTPException(status_code=404, detail="Datei noch nicht erzeugt.")

    @app.get("/jobs/{job_id}/review", response_class=HTMLResponse)
    def review_page(request: Request, job_id: str) -> HTMLResponse:
        job = _require_job(app.state.index, job_id)
        entries = _review_entries(app.state.index, job_id)
        return templates.TemplateResponse(request, "review.html", {"job": job, "entries": entries})

    @app.post("/jobs/{job_id}/review")
    async def review_save(job_id: str, request: Request) -> RedirectResponse:
        _require_job(app.state.index, job_id)
        form = await request.form()
        script_file = app.state.index.jobs_dir / job_id / "04_script" / "script.json"
        data = json.loads(script_file.read_text(encoding="utf-8")) if script_file.is_file() else {}
        chunks = data.get("chunks", [])
        for ci, chunk in enumerate(chunks):
            for bi, block in enumerate(chunk.get("blocks", [])):
                key = f"c{ci}b{bi}"
                if key in form:
                    block["text"] = str(form[key]).strip()
        _write_script_files(script_file, data, chunks)
        return RedirectResponse(f"/jobs/{job_id}/review", status_code=303)

    @app.post("/jobs/{job_id}/review/chunk", response_class=HTMLResponse)
    async def review_save_chunk(
        job_id: str, request: Request
    ) -> HTMLResponse:  # HTMX saves one chunk and swaps it back
        job = _require_job(app.state.index, job_id)
        form = await request.form()
        try:
            ci = int(str(form.get("ci", "")))
        except ValueError:
            raise HTTPException(status_code=400, detail="Chunk-Nummer fehlt.") from None
        script_file = app.state.index.jobs_dir / job_id / "04_script" / "script.json"
        data = json.loads(script_file.read_text(encoding="utf-8")) if script_file.is_file() else {}
        chunks = data.get("chunks", [])
        if ci < 0 or ci >= len(chunks):
            raise HTTPException(status_code=404, detail="Chunk nicht gefunden.")
        for bi, block in enumerate(chunks[ci].get("blocks", [])):
            key = f"c{ci}b{bi}"
            if key in form:
                block["text"] = str(form[key]).strip()
        _write_script_files(script_file, data, chunks)
        entry = _review_entries(app.state.index, job_id)[ci]
        return templates.TemplateResponse(
            request,
            "partials/review_chunk.html",
            {"job": job, "entry": entry, "saved_ci": ci, "saved": True},
        )

    @app.post("/jobs/{job_id}/speak")
    def speak_now(job_id: str) -> RedirectResponse:
        job = _require_job(app.state.index, job_id)
        job.options["resume_from"] = "speaking"
        job.error = ""
        app.state.index.update(job)
        app.state.worker.enqueue(job_id)
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    @app.post("/jobs/{job_id}/restart")
    def restart(job_id: str) -> RedirectResponse:
        job = _require_job(app.state.index, job_id)
        job.status = "queued"
        job.progress = 0
        job.error = ""
        job.options.pop("resume_from", None)
        app.state.index.update(job)
        app.state.worker.enqueue(job_id)
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    @app.post("/jobs/{job_id}/continue")
    def continue_job(job_id: str) -> RedirectResponse:
        job = _require_job(app.state.index, job_id)
        if job.status == "waiting_for_user" and not app.state.worker.continue_job(job_id):
            # no open gate (server restarted): queue the job again
            job.status = "queued"
            app.state.index.update(job)
            app.state.worker.enqueue(job_id)
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    @app.post("/tts-pool/start")
    def start_tts_pool() -> RedirectResponse:
        for job in app.state.index.list():
            if job.status == "awaiting_tts":
                job.options["resume_from"] = "speaking"
                app.state.index.update(job)
                app.state.worker.enqueue(job.id)
        return RedirectResponse("/", status_code=303)

    @app.get("/settings", response_class=HTMLResponse)
    def settings_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            request, "settings.html", {"config": config, "llm_result": "", "tts_result": ""}
        )

    @app.get("/settings/test-llm", response_class=HTMLResponse)
    def test_llm() -> HTMLResponse:
        from haldio.llm.client import LlmClient, LlmError

        try:
            client = LlmClient(config.llm)
            models = ", ".join(client.list_models()[:10])
            client.close()
            text = f"LM Studio ok: {models or 'keine Modelle'}"
        except LlmError as error:
            text = f"Fehler: {error}"
        except Exception as error:  # noqa: BLE001 - show any connection error in the UI
            text = f"Fehler: {error}"
        return HTMLResponse(_result_span(text))

    @app.post("/settings/test-tts")
    def test_tts() -> HTMLResponse:
        from haldio.tts import create_backend
        from haldio.tts.qwen_local import QwenLocalBackend

        backend = create_backend(config.tts)
        try:
            if isinstance(backend, QwenLocalBackend):
                try:
                    result = backend.check(
                        "Guten Tag. Dies ist ein Test der Sprachausgabe.",
                        Path("data") / "tts-check.wav",
                    )
                    voices = ", ".join(str(s) for s in result["speakers"][:10])
                    text = f"TTS ok: Stimmen {voices or 'keine'}"
                except Exception as error:  # noqa: BLE001 - show any worker error in the UI
                    text = f"Fehler: {error}"
            else:
                ok, message = backend.healthcheck()
                if ok:
                    names = ", ".join(v.name or v.id for v in backend.list_voices()[:10])
                    text = f"TTS ok: {names or 'keine Stimmen'}"
                else:
                    text = f"Fehler: {message}"
        except ModelGuardError as error:
            text = f"Gestoppt: {error}"
        finally:
            backend.close()
        return HTMLResponse(_result_span(text))

    @app.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str) -> RedirectResponse:
        _require_job(app.state.index, job_id)
        app.state.worker.cancel(job_id)
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    @app.post("/jobs/{job_id}/delete")
    def delete(job_id: str) -> RedirectResponse:
        _require_job(app.state.index, job_id)
        app.state.worker.cancel(job_id)
        app.state.index.delete(job_id)
        return RedirectResponse("/", status_code=303)

    return app


_DOWNLOADABLE = (
    "book.mp3",
    "book.ogg",
    "book.m4b",
    "merged.wav",
    "script.md",
    "qa_report.html",
    "source.pdf",
)

# result card slots: stored name -> German label shown in the UI
_FILE_SLOTS = (
    ("book.mp3", "MP3"),
    ("book.ogg", "OGG"),
    ("script.md", "Skript"),
    ("qa_report.html", "QA-Bericht"),
    ("source.pdf", "PDF"),
)


def _result_span(text: str) -> str:
    """Test-button result with a clear success/error/warn class."""
    cls = (
        "result-error"
        if text.startswith("Fehler")
        else "result-warn"
        if text.startswith("Gestoppt")
        else "result-ok"
    )  # noqa: E501
    return f'<span class="{cls}">{html.escape(text)}</span>'


def _format_date(value: str) -> str:
    """ISO stamp to a short German date; the raw value when unparsable."""
    try:
        return datetime.fromisoformat(value).strftime("%d.%m.%Y %H:%M")
    except (TypeError, ValueError):
        return str(value)


def _available_voices(config: Config) -> list[str]:
    """Voice ids from the last check_qwencpp.py run (data/voices.json), no server start."""
    path = Path(config.paths.data_dir) / "voices.json"
    names: list[str] = []
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            payload = []
        names = [str(v) for v in payload if str(v).strip()]
    if not names:
        names = [config.tts.speaker or "dylan"]
    return names


def _load_doc_map(index: JobIndex, job_id: str) -> dict[str, Any]:
    path = index.jobs_dir / job_id / "02_plan" / "doc_map.json"
    if not path.is_file():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _job_context(index: JobIndex, job_id: str, job: Job) -> dict[str, Any]:
    """Context shared by the job page and the polling status partial."""
    return {
        "job": job,
        "status": status_label(job.status),
        "stepper": stage_rows(
            job.status, str(job.activity.get("stage") or job.options.get("stage", ""))
        ),
        "files": _job_files(index, job),
        "has_script": _has_script(index, job_id),
        "summary": _load_doc_map(index, job_id),
        **_activity_info(job),
    }


def _activity_info(job: Job) -> dict[str, Any]:
    """Seconds since the last activity event and the stall warning flag."""
    activity = job.activity or {}
    age: int | None = None
    try:
        updated = datetime.fromisoformat(str(activity.get("updated_at", "")))
        age = max(0, int((datetime.now(UTC) - updated).total_seconds()))
    except (TypeError, ValueError):
        age = None
    stale = bool(age is not None and activity.get("state") == "running" and age >= 60)
    return {"activity_age": age, "activity_stale": stale}


def _review_entries(index: JobIndex, job_id: str) -> list[dict[str, Any]]:
    """Per chunk: script blocks, original text, chapter title and readable warnings."""
    folder = index.jobs_dir / job_id
    entries: list[dict[str, Any]] = []
    for ci, chunk in enumerate(_load_chunks(folder / "04_script" / "script.json")):
        original = ""
        chapter = ""
        src = folder / "03_edit" / "chunks" / f"{chunk.get('chunk_id', '')}.in.json"
        if src.is_file():
            try:
                src_data = json.loads(src.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                src_data = {}
            original = "\n".join(str(b.get("text", "")) for b in src_data.get("blocks", []))
            chapter = str(src_data.get("chapter_path") or "")
        entries.append(
            {
                "chunk": chunk,
                "ci": ci,
                "original": original,
                "chapter": chapter,
                "warnings": [warning_text(w) for w in chunk.get("warnings", [])],
                "needs_review": bool(chunk.get("needs_review")),
            }
        )
    return entries


def _write_script_files(script_file: Path, data: dict[str, Any], chunks: list[Any]) -> None:
    """Store the edited script.json and keep script.md and warnings in step."""
    data["chunks"] = chunks
    data["warnings"] = [w for c in chunks for w in c.get("warnings", [])]
    script_file.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    (script_file.parent / "script.md").write_text(render_script_md(chunks), encoding="utf-8")


async def _read_limited(file: UploadFile, limit: int) -> bytes:
    """Stream the upload in and stop as soon as it exceeds the size limit."""
    data = b""
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            return data
        data += chunk
        if len(data) > limit:
            raise HTTPException(status_code=413, detail="Datei zu groß für den Upload.")


def _require_job(index: JobIndex, job_id: str) -> Job:
    job = index.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nicht gefunden.")
    return job


def _job_files(index: JobIndex, job: Job) -> list[dict[str, Any]]:
    """Download slots that exist on disk; empty until the job is done."""
    if job.status != "done":
        return []
    folder = index.jobs_dir / job.id
    found: list[dict[str, Any]] = []
    for name, label in _FILE_SLOTS:
        for sub in ("06_master", "04_script", ""):
            path = folder / sub / name if sub else folder / name
            if path.is_file():
                found.append(
                    {
                        "name": name,
                        "label": label,
                        "url": f"/jobs/{job.id}/download/{name}",
                    }
                )
                break
    return found


def _download_name(job: Job, file_name: str) -> str:
    """Download file name from the PDF title (<Titel>.mp3), job id as fallback."""
    base = job.title or job.id
    slug = re.sub(r"[^\wÄÖÜäöüß.-]+", "_", base, flags=re.UNICODE).strip("_.") or job.id
    return f"{slug}{Path(file_name).suffix}"


def _has_script(index: JobIndex, job_id: str) -> bool:
    return (index.jobs_dir / job_id / "04_script" / "script.json").is_file()


def _load_chunks(script_file: Path) -> list[dict[str, Any]]:
    if not script_file.is_file():
        return []
    return list(json.loads(script_file.read_text(encoding="utf-8")).get("chunks", []))


def _format_seconds(value: float | int) -> str:
    minutes, secs = divmod(int(value), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min"
    return f"{secs} s"
