"""The audio job index stored on disk.

Jobs are stored in `data/jobs/<job_id>/`. The index is a single JSON file.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

STATUS_VALUES = (
    "queued",
    "extracting",
    "planning",
    "editing",
    "verifying",
    "awaiting_review",
    "speaking",
    "mastering",
    "done",
    "failed",
    "cancelled",
)


def new_job_id() -> str:
    return datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]


@dataclass
class Job:
    """One conversion job."""

    id: str
    file_name: str
    title: str = ""
    status: str = "queued"
    progress: int = 0
    message: str = ""
    language: str = "auto"
    created_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))
    page_count: int = 0
    audio_seconds: int = 0
    error: str = ""
    logs: list[str] = field(default_factory=list)
    options: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "file_name": self.file_name,
            "title": self.title,
            "status": self.status,
            "progress": self.progress,
            "message": self.message,
            "language": self.language,
            "created_at": self.created_at,
            "page_count": self.page_count,
            "audio_seconds": self.audio_seconds,
            "error": self.error,
            "logs": self.logs,
            "options": self.options,
        }


class JobIndex:
    """File-based job index."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.jobs_dir = self.data_dir / "jobs"
        self.index_file = self.data_dir / "index"
        self.jobs_dir.mkdir(parents=True, exist_ok=True)

    def create(self, file_name: str, options: dict[str, Any] | None = None) -> Job:
        job = Job(id=new_job_id(), file_name=file_name, options=options or {})
        self._write_job(job)
        self._save([job, *self.list()])
        return job

    def get(self, job_id: str) -> Job | None:
        data = self.jobs_dir / job_id / "job.json"
        if not data.is_file():
            return None
        return Job(**json.loads(data.read_text(encoding="utf-8")))

    def update(self, job: Job) -> None:
        self._write_job(job)
        jobs = self.list()
        for index, existing in enumerate(jobs):
            if existing.id == job.id:
                jobs[index] = job
                break
        self._save(jobs)

    def delete(self, job_id: str) -> None:
        import shutil

        folder = self.jobs_dir / job_id
        if folder.is_dir():
            shutil.rmtree(folder)
        self._save([job for job in self.list() if job.id != job_id])

    def list(self) -> list[Job]:
        if not self.index_file.is_file():
            return []
        raw = json.loads(self.index_file.read_text(encoding="utf-8"))
        return [Job(**item) for item in raw]

    def _write_job(self, job: Job) -> None:
        folder = self.jobs_dir / job.id
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "job.json"
        path.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

    def _save(self, jobs: list[Job]) -> None:
        self.index_file.write_text(
            json.dumps([job.to_dict() for job in jobs], ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
