"""FastAPI web UI (German): library page, job page, downloads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from haldio import __version__
from haldio.config import Config
from haldio.jobs.index import Job, JobIndex
from haldio.jobs.worker import Worker

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
    app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

    @app.get("/", response_class=HTMLResponse)
    def library(request: Request) -> HTMLResponse:
        jobs = app.state.index.list()
        return templates.TemplateResponse(
            request, "library.html", {"jobs": jobs, "version": __version__}
        )

    @app.post("/upload")
    async def upload(
        file: UploadFile = File(...),
        voice: str = Form(""),  # noqa: B008 - FastAPI pattern
    ) -> RedirectResponse:
        name = file.filename or "upload.pdf"
        if not name.lower().endswith(".pdf"):
            raise HTTPException(status_code=400, detail="Nur PDF-Dateien sind erlaubt.")
        data = await file.read()
        limit = config.server.max_upload_mb * 1024 * 1024
        if len(data) > limit:
            raise HTTPException(status_code=413, detail="Datei zu groß für den Upload.")
        job = app.state.index.create(name, options={"voice": voice})
        folder = app.state.index.jobs_dir / job.id
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "source.pdf").write_bytes(data)
        app.state.worker.enqueue(job.id)
        return RedirectResponse(f"/jobs/{job.id}", status_code=303)

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_page(request: Request, job_id: str) -> HTMLResponse:
        job = _require_job(app.state.index, job_id)
        return templates.TemplateResponse(
            request, "job.html", {"job": job, "files": _job_files(job)}
        )

    @app.get("/jobs/{job_id}/status", response_class=HTMLResponse)
    def job_status(request: Request, job_id: str) -> HTMLResponse:
        job = _require_job(app.state.index, job_id)
        return templates.TemplateResponse(
            request, "partials/job_status.html", {"job": job, "files": _job_files(job)}
        )

    @app.get("/jobs/{job_id}/download/{file_name}")
    def download(job_id: str, file_name: str) -> FileResponse:
        _require_job(app.state.index, job_id)
        if file_name not in _DOWNLOADABLE:
            raise HTTPException(status_code=404, detail="Unbekannte Datei.")
        candidates = [
            app.state.index.jobs_dir / job_id / "06_master" / file_name,
            app.state.index.jobs_dir / job_id / "04_script" / file_name,
            app.state.index.jobs_dir / job_id / file_name,
        ]
        for path in candidates:
            if path.is_file():
                return FileResponse(path, filename=f"{job_id}-{file_name}")
        raise HTTPException(status_code=404, detail="Datei noch nicht erzeugt.")

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
)


def _require_job(index: JobIndex, job_id: str) -> Job:
    job = index.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nicht gefunden.")
    return job


def _job_files(job: Job) -> list[dict[str, Any]]:
    if job.status != "done":
        return []
    return [{"name": name, "available": True} for name in _DOWNLOADABLE]


def _format_seconds(value: float | int) -> str:
    minutes, secs = divmod(int(value), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min"
    return f"{secs} s"
