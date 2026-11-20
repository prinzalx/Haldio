"""Background worker: runs conversion jobs from a FIFO queue in one thread."""

from __future__ import annotations

import threading
import traceback
from collections import deque
from collections.abc import Callable
from pathlib import Path
from typing import Any

from haldio.config import Config
from haldio.jobs.index import JobIndex
from haldio.pipeline.run import BookResult, run_book, run_speech

_ACTIVE_STATUSES = ("queued", "extracting", "planning", "editing", "speaking", "mastering")


class _Cancelled(Exception):
    pass


class Worker:
    """Runs one job at all stages; jobs wait in a FIFO queue."""

    def __init__(
        self,
        index: JobIndex,
        config: Config,
        run_fn: Callable[..., BookResult] | None = None,
        inline: bool = False,
    ) -> None:
        self.index = index
        self.config = config
        self._run_fn = run_fn or run_book
        self._inline = inline
        self._queue: deque[str] = deque()
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._cancelled: set[str] = set()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Re-queue jobs interrupted by a crash and start the thread."""
        for job in self.index.list():
            if job.status in _ACTIVE_STATUSES:
                job.status = "queued"
                job.message = "erneut eingereiht"
                self.index.update(job)
                self.enqueue(job.id)
        if self._inline:
            return
        if self._thread is None or not self._thread.is_alive():
            self._thread = threading.Thread(target=self._loop, daemon=True)
            self._thread.start()

    def enqueue(self, job_id: str) -> None:
        with self._lock:
            known = job_id in self._queue
            if not known:
                self._queue.append(job_id)
        self._wake.set()
        if self._inline and not known:
            with self._lock:
                self._queue.remove(job_id)
            self._process(job_id)

    def cancel(self, job_id: str) -> None:
        self._cancelled.add(job_id)
        job = self.index.get(job_id)
        if job is not None and job.status in ("queued", "awaiting_tts"):
            if job.status == "queued":
                with self._lock:
                    if job_id in self._queue:
                        self._queue.remove(job_id)
            job.status = "cancelled"
            self.index.update(job)

    def _loop(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    self._wake.clear()
                    if not self._queue:
                        self._wake.wait(1.0)
                        continue
                job_id = self._queue.popleft()
            self._process(job_id)

    def _process(self, job_id: str) -> None:
        job = self.index.get(job_id)
        if job is None or job.status == "cancelled":
            return

        def progress(stage: str, value: int) -> None:
            if job_id in self._cancelled:
                raise _Cancelled()
            job.status = stage
            job.progress = value
            self.index.update(job)

        try:
            folder = self.index.jobs_dir / job_id
            if job.options.get("resume_from") == "speaking":
                language = job.language if job.language in ("de", "en") else "de"
                result = run_speech(folder, self.config, language, progress=progress)
            else:
                result = self._run_fn(
                    folder / "source.pdf",
                    self.config,
                    folder,
                    progress=progress,
                    stop_after_script=self.config.editor.review_before_tts,
                    stop_before_tts=self.config.tts.confirm_before_start,
                )
            if job_id in self._cancelled:
                raise _Cancelled()
            if result.review_paused:
                job.status = "awaiting_review"
                job.progress = 60
                job.error = ""
            elif result.tts_gate:
                job.status = "awaiting_tts"
                job.progress = 60
                job.error = ""
                job.message = "Bereit für Sprachausgabe"
            else:
                job.status = "done" if result.return_code == 0 else "failed"
                job.progress = 100 if result.return_code == 0 else job.progress
                job.error = result.script.error or result.speak.error or result.master.error
                if job.status == "done":
                    job.audio_seconds = int(result.speak.total_seconds)
            self.index.update(job)
        except _Cancelled:
            job.status = "cancelled"
            self.index.update(job)
        except Exception as error:  # noqa: BLE001 - a job failure must not kill the thread
            job.status = "failed"
            job.error = str(error)
            job.message = traceback.format_exc(limit=1).strip()
            self.index.update(job)


def job_folder(index: JobIndex, job_id: str) -> Path:
    return index.jobs_dir / job_id


def save_upload(index: JobIndex, job_id: str, data: bytes, file_name: str) -> dict[str, Any]:
    folder = job_folder(index, job_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "source.pdf").write_bytes(data)
    return {"saved": str(folder / "source.pdf"), "file_name": file_name}
