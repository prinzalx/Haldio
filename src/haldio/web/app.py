"""FastAPI web UI (German): library page, job page, downloads."""

from __future__ import annotations

import html
import json
import re
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, Response, UploadFile
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from haldio import __version__
from haldio.config import Config
from haldio.jobs.index import Job, JobIndex
from haldio.jobs.worker import Worker
from haldio.llm import LlmClient
from haldio.llm.client import llm_reachable, loaded_llm_models
from haldio.pipeline.assemble import render_script_md
from haldio.pipeline.edit import load_prompt_version, system_with_examples
from haldio.pipeline.run import edit_chunk_with_retry
from haldio.settings_store import (
    clear_override,
    effective_config,
    load_override,
    parse_form,
    save_override,
)
from haldio.tts.base import ModelGuardError
from haldio.web.labels import stage_help, status_label, stepper_state, warning_text
from haldio.web.voices import speaker_rows

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
    templates.env.globals["version"] = __version__  # footer + settings only
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
                "voices": _available_voices(config),
                "selected_voice": config.tts.speaker or "dylan",
            },
        )

    @app.post("/upload")
    async def upload(
        file: list[UploadFile] = File(...),  # noqa: B008 - FastAPI pattern
        voice: str = Form("dylan"),
        language: str = Form("auto"),
        review: bool = Form(False),
    ) -> RedirectResponse:
        """Stapel-Upload: one job per PDF, all run through the queue in order."""
        if not file:
            raise HTTPException(status_code=400, detail="Keine Datei gewählt.")
        limit = config.server.max_upload_mb * 1024 * 1024
        # read and validate ALL files first, so a bad one cannot leave half a batch
        payloads = []
        for one in file:
            name = one.filename or "upload.pdf"
            if not name.lower().endswith(".pdf"):
                raise HTTPException(status_code=400, detail="Nur PDF-Dateien sind erlaubt.")
            data = await _read_limited(one, limit)
            if not data.startswith(b"%PDF-"):
                raise HTTPException(status_code=400, detail="Datei ist kein PDF (Magic Bytes).")
            payloads.append((name, data))
        options = {"voice": voice, "language": language, "review": review}
        created = []
        for name, data in payloads:
            job = app.state.index.create(name, options=dict(options))
            if language in ("de", "en"):
                job.language = language
                app.state.index.update(job)
            folder = app.state.index.jobs_dir / job.id
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "source.pdf").write_bytes(data)
            created.append(job)
        for job in created:
            app.state.worker.enqueue(job.id)
        if len(created) == 1:
            return RedirectResponse(f"/jobs/{created[0].id}", status_code=303)
        return RedirectResponse("/", status_code=303)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(request: Request, job_id: str) -> HTMLResponse:
        job = _require_job(app.state.index, job_id)
        context = _job_context(app.state.index, job_id, job, config)
        if context["has_script"]:
            context["review_hints"] = _hint_count(_review_entries(app.state.index, job_id))
        return templates.TemplateResponse(request, "job.html", context)

    @app.get("/api/jobs/{job_id}")
    def job_api(job_id: str) -> dict[str, Any]:
        return _require_job(app.state.index, job_id).to_dict()

    @app.get("/jobs/{job_id}/status", response_class=HTMLResponse)
    def job_status(request: Request, job_id: str) -> HTMLResponse:
        job = _require_job(app.state.index, job_id)
        return templates.TemplateResponse(
            request,
            "partials/job_status.html",
            _job_context(app.state.index, job_id, job, config),
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
        return templates.TemplateResponse(
            request,
            "review.html",
            {
                "job": job,
                "entries": entries,
                "hint_count": _hint_count(entries),
                "llm_ok": llm_reachable(config.llm),
            },
        )

    @app.post("/jobs/{job_id}/review")
    async def review_save(job_id: str, request: Request) -> RedirectResponse:
        _require_job(app.state.index, job_id)
        form = await request.form()
        script_file = app.state.index.jobs_dir / job_id / "04_script" / "script.json"
        data = json.loads(script_file.read_text(encoding="utf-8")) if script_file.is_file() else {}
        chunks = data.get("chunks", [])
        for ci, chunk in enumerate(chunks):
            _apply_chunk_form(chunk, form, ci)
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
        _apply_chunk_form(chunks[ci], form, ci)
        _write_script_files(script_file, data, chunks)
        entry = _review_entries(app.state.index, job_id)[ci]
        return templates.TemplateResponse(
            request,
            "partials/review_chunk.html",
            {"job": job, "entry": entry, "saved_ci": ci, "saved": True},
        )

    @app.post("/jobs/{job_id}/review/use_original", response_class=HTMLResponse)
    async def review_use_original(job_id: str, request: Request) -> HTMLResponse:
        """Empty script section: copy the ORIGINAL text in as the spoken text."""
        job = _require_job(app.state.index, job_id)
        form = await request.form()
        ci = _form_ci(form)
        script_file = app.state.index.jobs_dir / job_id / "04_script" / "script.json"
        data = json.loads(script_file.read_text(encoding="utf-8")) if script_file.is_file() else {}
        chunks = data.get("chunks", [])
        if ci >= len(chunks):
            raise HTTPException(status_code=404, detail="Chunk nicht gefunden.")
        original = _review_entries(app.state.index, job_id)[ci]["original"]
        if not original.strip():
            raise HTTPException(status_code=409, detail="Kein Originaltext gefunden.")
        chunks[ci]["blocks"] = [{"kind": "paragraph", "level": None, "text": original.strip()}]
        _write_script_files(script_file, data, chunks)
        entry = _review_entries(app.state.index, job_id)[ci]
        return templates.TemplateResponse(
            request,
            "partials/review_chunk.html",
            {"job": job, "entry": entry, "saved_ci": ci, "saved": True},
        )

    @app.post("/jobs/{job_id}/review/regenerate", response_class=HTMLResponse)
    async def review_regenerate(job_id: str, request: Request) -> HTMLResponse:
        """Empty script section: ask the editor LLM for a new Hörtext."""
        job = _require_job(app.state.index, job_id)
        form = await request.form()
        ci = _form_ci(form)
        script_file = app.state.index.jobs_dir / job_id / "04_script" / "script.json"
        data = json.loads(script_file.read_text(encoding="utf-8")) if script_file.is_file() else {}
        chunks = data.get("chunks", [])
        if ci >= len(chunks):
            raise HTTPException(status_code=404, detail="Chunk nicht gefunden.")
        src = (
            app.state.index.jobs_dir
            / job_id
            / "03_edit"
            / "chunks"
            / f"{chunks[ci].get('chunk_id', '')}.in.json"
        )
        if not src.is_file():
            raise HTTPException(status_code=409, detail="Kein Originaltext gefunden.")
        chunk_input = json.loads(src.read_text(encoding="utf-8"))
        error = ""
        edit = None
        try:
            system_prompt, examples = load_prompt_version(config)
            client = LlmClient(config.llm)
            try:
                edit, _issues = edit_chunk_with_retry(
                    chunk_input,
                    client,
                    system_with_examples(system_prompt, examples),
                    str(job.options.get("language") or "de"),
                    config.editor.max_retries,
                )
            finally:
                client.close()
        except Exception as exc:  # noqa: BLE001 - the page must stay usable
            edit, error = None, f"Sprachmodell nicht erreichbar: {exc}"
        if edit is not None and edit.result is not None and edit.result.blocks:
            chunks[ci]["blocks"] = [b.model_dump() for b in edit.result.blocks]
            chunks[ci]["warnings"] = [w.type for w in edit.result.warnings]
            chunks[ci]["needs_review"] = edit.needs_review
            _write_script_files(script_file, data, chunks)
        entry = _review_entries(app.state.index, job_id)[ci]
        return templates.TemplateResponse(
            request,
            "partials/review_chunk.html",
            {
                "job": job,
                "entry": entry,
                "saved_ci": ci,
                "saved": edit is not None,
                "regen_error": error,
                "llm_ok": not error,
            },
        )

    def _action_redirect(request: Request, job_id: str) -> RedirectResponse:
        """HTMX calls get the fresh status block; plain forms get the page."""
        if request.headers.get("hx-request"):
            return RedirectResponse(f"/jobs/{job_id}/status", status_code=303)
        return RedirectResponse(f"/jobs/{job_id}", status_code=303)

    @app.post("/jobs/{job_id}/speak")
    def speak_now(job_id: str, request: Request) -> RedirectResponse:
        job = _require_job(app.state.index, job_id)
        job.options["resume_from"] = "speaking"
        job.error = ""
        app.state.index.update(job)
        app.state.worker.enqueue(job_id)
        return _action_redirect(request, job_id)

    @app.post("/jobs/{job_id}/restart")
    def restart(job_id: str, request: Request) -> RedirectResponse:
        job = _require_job(app.state.index, job_id)
        job.status = "queued"
        job.progress = 0
        job.error = ""
        job.options.pop("resume_from", None)
        app.state.index.update(job)
        app.state.worker.enqueue(job_id)
        return _action_redirect(request, job_id)

    @app.post("/jobs/{job_id}/continue")
    def continue_job(job_id: str, request: Request) -> RedirectResponse:
        job = _require_job(app.state.index, job_id)
        if job.status == "waiting_for_user" and not app.state.worker.continue_job(job_id):
            # no open gate (server restarted): queue the job again
            job.status = "queued"
            app.state.index.update(job)
            app.state.worker.enqueue(job_id)
        return _action_redirect(request, job_id)

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
        eff = effective_config(config)
        return templates.TemplateResponse(
            request,
            "settings.html",
            {
                "config": eff,
                "form": _form_from_config(eff),
                "errors": {},
                **_speaker_context(config, eff),
            },
        )

    @app.post("/settings")
    async def save_settings(request: Request) -> Response:
        data = dict(await request.form())
        values, errors = parse_form(data)
        if errors:
            eff = effective_config(config)
            return templates.TemplateResponse(
                request,
                "settings.html",
                {
                    "config": eff,
                    "form": data,
                    "errors": errors,
                    **_speaker_context(config, eff, data.get("tts.speaker", "")),
                },
                status_code=422,
            )
        merged = load_override(config.paths.data_dir)
        for section, updates in values.items():
            merged.setdefault(section, {}).update(updates)  # type: ignore[union-attr]
        save_override(config.paths.data_dir, merged)
        return RedirectResponse("/settings?saved=1", status_code=303)

    @app.post("/settings/reset")
    def reset_settings() -> RedirectResponse:
        clear_override(config.paths.data_dir)
        return RedirectResponse("/settings?reset=1", status_code=303)

    @app.get("/dokumentation", response_class=PlainTextResponse)
    def dokumentation() -> PlainTextResponse:
        """The settings manual; paths live in the docs, not in the UI."""
        path = Path(__file__).resolve().parents[3] / "docs" / "configuration.md"
        if not path.is_file():
            raise HTTPException(status_code=404)
        return PlainTextResponse(path.read_text(encoding="utf-8"))

    @app.get("/settings/test-llm", response_class=HTMLResponse)
    def test_llm() -> HTMLResponse:
        from haldio.llm.client import LlmClient, LlmError

        llm = effective_config(config).llm
        try:
            client = LlmClient(llm)
            models = client.list_models()
            client.close()
        except LlmError as error:
            return HTMLResponse(_result_span(f"Fehler: {error}"))
        except Exception as error:  # noqa: BLE001 - show any connection error in the UI
            return HTMLResponse(_result_span(f"Fehler: {error}"))
        count = f"{len(models)} Modell{'e' if len(models) != 1 else ''}"
        if llm.model in models:
            text = f"LM Studio ok: {count} · gewähltes Modell vorhanden"
        else:
            text = f"Achtung: LM Studio ok ({count}) · Modell {llm.model} fehlt"
        return HTMLResponse(_result_span(text))

    @app.get("/settings/models")
    def models_list() -> JSONResponse:
        """The LM Studio model list for the dropdown, plus which are loaded."""
        from haldio.llm.client import LlmClient

        llm = effective_config(config).llm
        try:
            client = LlmClient(llm)
            models = client.list_models()
            client.close()
        except Exception as error:  # noqa: BLE001 - shown as a hint
            return JSONResponse({"ok": False, "error": str(error)})
        return JSONResponse(
            {
                "ok": True,
                "models": models,
                "loaded": loaded_llm_models() or [],
                "current": llm.model,
            }
        )

    @app.post("/settings/test-tts")
    def test_tts() -> HTMLResponse:
        from haldio.tts import create_backend
        from haldio.tts.qwen_local import QwenLocalBackend

        backend = None
        try:
            backend = create_backend(effective_config(config).tts)
            if isinstance(backend, QwenLocalBackend):
                try:
                    result = backend.check(
                        "Guten Tag. Dies ist ein Test der Sprachausgabe.",
                        config.paths.data_dir / "tts-check.wav",
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
            if backend is not None:
                backend.close()
        return HTMLResponse(_result_span(text))

    @app.get("/samples/{voice}.wav")
    def sample_audio(voice: str) -> FileResponse:
        path = _sample_dir(config) / f"{voice}.wav"
        if not _SAFE_VOICE.fullmatch(voice) or not path.is_file():
            raise HTTPException(status_code=404)
        return FileResponse(path, media_type="audio/wav")

    @app.post("/settings/sample", response_class=HTMLResponse)
    def make_sample(
        voice: str = Form(...),  # noqa: B008 - FastAPI pattern
        text: str = Form(""),
        language: str = Form("auto"),
    ) -> HTMLResponse:
        """Hörprobe für eine Stimme; startet den TTS-Server durch den Modell-Guard."""
        from haldio.tts import create_backend
        from haldio.tts.base import TTSParams

        if not _SAFE_VOICE.fullmatch(voice):
            raise HTTPException(status_code=404)
        lang = language if language in ("de", "en") else "auto"
        probe = " ".join(text.split())[:200]
        if not probe:
            probe = _PROBE_TEXTS["en" if lang == "en" else "de"]
        backend = None
        try:
            backend = create_backend(effective_config(config).tts)
            audio = backend.synthesize(probe, lang, TTSParams(voice=voice))
            out = _sample_dir(config) / f"{voice}.wav"
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(audio.data)
            stamp = int(datetime.now(UTC).timestamp())
            body = (
                '<span class="result-ok">Hörprobe fertig</span> '
                f'<audio controls src="/samples/{voice}.wav?v={stamp}"></audio>'
            )
            return HTMLResponse(body)
        except ModelGuardError as error:
            return HTMLResponse(_result_span(f"Gestoppt: {error}"))
        except Exception as error:  # noqa: BLE001 - show any TTS error in the UI
            return HTMLResponse(_result_span(f"Fehler: {error}"))
        finally:
            if backend is not None:
                backend.close()

    @app.post("/jobs/{job_id}/cancel")
    def cancel(job_id: str, request: Request) -> RedirectResponse:
        _require_job(app.state.index, job_id)
        app.state.worker.cancel(job_id)
        return _action_redirect(request, job_id)

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


def _form_from_config(cfg: Config) -> dict[str, str]:
    """Effective values as form strings, so one template shape serves GET and POST."""
    return {
        "llm.base_url": cfg.llm.base_url,
        "llm.model": cfg.llm.model,
        "tts.speaker": cfg.tts.speaker,
        "tts.qwencpp_model": cfg.tts.qwencpp_model,
        "tts.language": cfg.tts.language,
        "audio.format.mp3": "on" if "mp3" in cfg.audio.formats else "",
        "audio.format.ogg": "on" if "ogg" in cfg.audio.formats else "",
        "audio.mp3_bitrate_kbps": str(cfg.audio.mp3_bitrate_kbps),
        "audio.pause_ms.paragraph": _secs(cfg.audio.pause_ms.paragraph),
        "audio.pause_ms.heading": _secs(cfg.audio.pause_ms.heading),
        "audio.pause_ms.chapter": _secs(cfg.audio.pause_ms.chapter),
        "llm.timeout_s": str(cfg.llm.timeout_s),
        "llm.temperature": _comma(cfg.llm.temperature),
        "tts.max_chars_per_unit": str(cfg.tts.max_chars_per_unit),
        "tts.qwencpp_port": str(cfg.tts.qwencpp_port),
        "tts.qwencpp_startup_timeout": str(cfg.tts.qwencpp_startup_timeout),
        "editor.review_before_tts": "on" if cfg.editor.review_before_tts else "",
        "tts.confirm_before_start": "on" if cfg.tts.confirm_before_start else "",
        "editor.fallback_to_source": "on" if cfg.editor.fallback_to_source else "",
        "editor.max_retries": str(cfg.editor.max_retries),
    }


_SAFE_VOICE = re.compile(r"[A-Za-z0-9_.-]{1,40}")
# default probe texts per language (used when the test-text field is empty)
_PROBE_TEXTS = {
    "de": "Guten Tag. Dies ist eine Hörprobe.",
    "en": "Hello. This is a voice sample.",
}


def _secs(ms: int) -> str:
    """Milliseconds as German seconds text (500 -> "0,5")."""
    return _comma(ms / 1000)


def _comma(value: float) -> str:
    return f"{value:g}".replace(".", ",")


def _sample_dir(cfg: Config) -> Path:
    return cfg.paths.data_dir / "samples"


def _speaker_context(base: Config, eff: Config, selected: str | None = None) -> dict[str, Any]:
    """Speaker radio rows (chosen one flagged, sample flag set) plus quality options."""
    rows = speaker_rows(selected or eff.tts.speaker or "dylan")
    for row in rows:
        row["sample"] = (_sample_dir(base) / f"{row['id']}.wav").is_file()
    return {"speakers": rows, "qualities": _quality_options(eff)}


def _quality_options(cfg: Config) -> list[dict[str, str]]:
    """Talker model files that exist on disk, plain-word labels, no paths shown."""

    def label_of(name: str) -> str:
        if "Q8" in name:
            return "Standard (Q8)"
        if "Q4" in name:
            return "Kleiner und schneller (Q4)"
        return name

    models_dir = Path(cfg.tts.qwencpp_model).parent
    options = [
        {"path": str(path), "label": label_of(path.name)}
        for path in sorted(models_dir.glob("qwen-talker-*.gguf"))
    ]
    if not options:
        fallback = Path(cfg.tts.qwencpp_model)
        options = [{"path": str(fallback), "label": label_of(fallback.name)}]
    return options


def _result_span(text: str) -> str:
    """Test-button result with a clear success/error/warn class."""
    cls = (
        "result-error"
        if text.startswith(("Fehler", "CSRF"))
        else "result-warn"
        if text.startswith(("Gestoppt", "Achtung"))
        else "result-ok"
    )
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


def _job_context(index: JobIndex, job_id: str, job: Job, config: Config) -> dict[str, Any]:
    """Context shared by the job page and the polling status partial."""
    return {
        "job": job,
        "status": status_label(job.status),
        "stepper": stepper_state(job),
        "stage_help": stage_help(),
        "files": _job_files(index, job),
        "has_script": _has_script(index, job_id),
        "summary": _load_doc_map(index, job_id),
        "voice": str(job.options.get("voice") or config.tts.speaker or "dylan"),
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


def _form_ci(form: Mapping[str, str]) -> int:
    try:
        return int(str(form.get("ci", "")))
    except ValueError:
        raise HTTPException(status_code=400, detail="Chunk-Nummer fehlt.") from None


def _apply_chunk_form(chunk: dict[str, Any], form: Mapping[str, str], ci: int) -> None:
    """Write every c{ci}b{index} form field into the chunk (adds missing blocks)."""
    prefix = f"c{ci}b"
    blocks = chunk.setdefault("blocks", [])
    for key in form:
        if not str(key).startswith(prefix):
            continue
        try:
            bi = int(str(key)[len(prefix) :])
        except ValueError:
            continue
        while len(blocks) <= bi:
            blocks.append({"kind": "paragraph", "level": None, "text": ""})
        blocks[bi]["text"] = str(form[key]).strip()


def _hint_count(entries: list[dict[str, Any]]) -> int:
    """Sections with warnings, a review mark or a missing Hörtext."""
    return sum(1 for e in entries if e["warnings"] or e["needs_review"] or e["empty"])


def _block_display(block: dict[str, Any]) -> str:
    """Readable text of one chunk block for the Original column.

    Tables keep their content in cells and lists in list_items; the plain
    text field can be blank there, so fall back to those before hiding the
    block.
    """
    text = str(block.get("text", "")).strip()
    if text:
        return text
    cells = block.get("cells") or []
    if cells:
        return "; ".join(" ".join(str(cell) for cell in row).strip() for row in cells)
    items = block.get("list_items") or []
    return "; ".join(str(i.get("text", "")) for i in items if isinstance(i, dict))


def _review_entries(index: JobIndex, job_id: str) -> list[dict[str, Any]]:
    """Per chunk: script blocks, original text, chapter title and readable warnings."""
    folder = index.jobs_dir / job_id
    entries: list[dict[str, Any]] = []
    for ci, chunk in enumerate(_load_chunks(folder / "04_script" / "script.json")):
        original = ""
        chapter = ""
        page = None
        src = folder / "03_edit" / "chunks" / f"{chunk.get('chunk_id', '')}.in.json"
        if src.is_file():
            try:
                src_data = json.loads(src.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                src_data = {}
            original = "\n".join(_block_display(b) for b in src_data.get("blocks", []))
            chapter = str(src_data.get("chapter_path") or "")
            span = src_data.get("page_span")
            if isinstance(span, list) and span and isinstance(span[0], int):
                page = span[0]
        entries.append(
            {
                "chunk": chunk,
                "ci": ci,
                "original": original,
                "chapter": chapter,
                "page": page,
                "empty": not any(str(b.get("text", "")).strip() for b in chunk.get("blocks", [])),
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
