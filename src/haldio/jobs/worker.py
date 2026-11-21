"""Background worker: runs conversion jobs from a FIFO queue in one thread."""

from __future__ import annotations

import logging
import re
import threading
import time
import traceback
from collections import deque
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from haldio.config import Config
from haldio.jobs.index import Job, JobIndex
from haldio.llm.client import loaded_llm_models
from haldio.pipeline.run import BookResult, run_book, run_speech
from haldio.tts.base import ModelGuardError

_ACTIVE_STATUSES = ("queued", "extracting", "planning", "editing", "speaking", "mastering")
_LOG_TAIL = 200
_STAGE_LABELS = {
    "extracting": "Einlesen",
    "planning": "Planen",
    "editing": "Hörtext schreiben",
    "verifying": "Kontrollieren",
    "script": "Skript erstellen",
    "speaking": "Vorlesen",
    "mastering": "Audio fertigstellen",
}
# word used to count per-item progress in each stage
_ITEM_WORDS = {
    "editing": "Abschnitt",
    "verifying": "Abschnitt",
    "speaking": "Einheit",
    "mastering": "Teil",
}
# note markers that describe a real (measured) item; cache hits and silent
# failures are excluded from the speed average
_REAL_MARKERS = ("", "ok", "synth")
# the extracting summary note ("12 Seiten gelesen") carries the page count
_PAGES_RE = re.compile(r"(\d+) Seiten")
_CONSOLE = logging.getLogger("haldio.worker")


def _fallback_title(meta: dict[str, Any], file_name: str) -> str:
    """PDF without metadata title: first top-level heading, else filename stem."""
    for chapter in meta.get("chapters") or []:
        if int(chapter.get("level", 1)) != 1:
            continue
        title = str(chapter.get("title", "")).strip()
        if title:
            return title
    return Path(file_name).stem


class _Cancelled(Exception):
    pass


def _format_eta(seconds: int) -> str:
    minutes, secs = divmod(max(0, seconds), 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours} h {minutes} min"
    if minutes:
        return f"{minutes} min"
    return f"{secs} s"


def _parse_note(note: str) -> tuple[int, int, str, str]:
    """Split a pipeline note into (done, total, marker, extra text).

    Grammar: "<done>/<total> <extra> #<marker>"; marker is one of
    ok / cache / fail / summary. Extra text is German and goes to the log.
    """
    marker = ""
    if "#" in note:
        note, _, marker = note.rpartition("#")
        marker = marker.strip()
        note = note.strip()
    done = total = 0
    head, _, rest = note.partition(" ")
    if "/" in head:
        a, _, b = head.partition("/")
        if a.isdigit() and b.isdigit():
            done, total = int(a), int(b)
    return done, total, marker, rest.strip()


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
        self._gates: dict[str, threading.Event] = {}
        self._job_logs: dict[str, deque[str]] = {}
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        """Re-queue jobs interrupted by a crash and start the thread."""
        for job in self.index.list():
            if job.status in _ACTIVE_STATUSES + ("waiting_for_user",):
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
        if job is not None and job.status in ("queued", "awaiting_tts", "waiting_for_user"):
            if job.status == "queued":
                with self._lock:
                    if job_id in self._queue:
                        self._queue.remove(job_id)
            job.status = "cancelled"
            self.index.update(job)

    def continue_job(self, job_id: str) -> bool:
        """Release a stage that waits in waiting_for_user; False when none is open."""
        with self._lock:
            event = self._gates.get(job_id)
        if event is None:
            return False
        event.set()
        return True

    def _log_lines(self, job_id: str) -> deque[str]:
        return self._job_logs.setdefault(job_id, deque(maxlen=_LOG_TAIL))

    def _log(self, job: Job, body: str, level: str = "INFO") -> None:
        """One line per real event: timestamp, level, readable text.

        Repeating the same text is skipped so a polling loop never fills
        the log with duplicates. Lines go to memory, logs/job.log and the
        serve console (stdlib logging).
        """
        stamp = datetime.now(UTC).strftime("%H:%M:%S")
        entry = f"{stamp} [{level}] {body}"
        lines = self._log_lines(job.id)
        if lines and lines[-1].split("] ", 1)[-1] == body:
            return
        lines.append(entry)
        job.logs = list(lines)
        _CONSOLE.info(entry)
        try:
            path = self.index.jobs_dir / job.id / "logs" / "job.log"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as handle:
                handle.write(entry + "\n")
        except OSError:
            pass

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
        # an old cancel flag must not kill a job the user resumed
        self._cancelled.discard(job_id)
        # re-seed the in-memory tail so a restart keeps the last log lines
        self._job_logs[job_id] = deque(job.logs[-_LOG_TAIL:], maxlen=_LOG_TAIL)

        # per-stage item timing feeds the ETA rule: average of the last 10
        # real items, shown only after 5 real items (cache hits never count)
        tracks: dict[str, dict[str, Any]] = {}

        def emit(
            state: str,
            stage: str = "",
            detail: str = "",
            eta: int | None = None,
            done: int = 0,
            total: int = 0,
        ) -> None:
            """Write the ONE activity record every UI part reads from."""
            job.activity = {
                "state": state,
                "stage": stage,
                "done": done,
                "total": total,
                "detail": detail,
                "eta": eta,
                "updated_at": datetime.now(UTC).isoformat(timespec="seconds"),
            }

        def progress(stage: str, value: int, note: str = "") -> None:
            if job_id in self._cancelled:
                raise _Cancelled()
            done, total, marker, extra = _parse_note(note)
            if stage != job.status:
                self._log(job, f"{_STAGE_LABELS.get(stage, stage)}: gestartet")
            job.status = stage
            job.progress = value
            job.options["stage"] = stage
            track = tracks.setdefault(
                stage, {"last_done": 0, "last_time": None, "durations": deque(maxlen=10), "real": 0}
            )
            now = time.monotonic()
            level = "INFO"
            if done and total:
                delta = None
                if done > track["last_done"]:
                    if track["last_time"] is not None:
                        delta = now - float(track["last_time"])
                    track["last_done"] = done
                    track["last_time"] = now
                    if marker in _REAL_MARKERS and delta is not None:
                        track["durations"].append(delta)
                        track["real"] += 1
                eta: int | None = None
                if track["real"] >= 5 and track["durations"] and done < total:
                    avg = sum(track["durations"]) / len(track["durations"])
                    eta = int((total - done) * avg)
                word = _ITEM_WORDS.get(stage, "Abschnitt")
                detail = f"{word} {done} von {total}"
                if eta is not None:
                    detail += f" · noch etwa {_format_eta(eta)}"
                elif stage == "mastering" and extra:
                    detail += f": {extra}"
                if marker == "cache":
                    body = f"{word} {done}/{total} {extra or 'aus dem Zwischenspeicher übernommen'}"
                elif marker == "fail":
                    body = f"{word} {done}/{total} {extra or 'fehlgeschlagen, Stille eingesetzt'}"
                    level = "WARN"
                elif marker == "summary":
                    body = extra or detail
                elif delta is not None:
                    body = f"{word} {done}/{total} fertig nach {delta:.0f} s"
                    body = f"{body} {extra}" if extra else body
                else:
                    body = f"{word} {done}/{total} {extra}".strip()
                emit("running", stage, detail, eta, done, total)
                self._log(job, f"{_STAGE_LABELS.get(stage, stage)}: {body}", level)
            else:
                detail = extra or _STAGE_LABELS.get(stage, stage)
                if stage == "extracting":
                    # _parse_note moved the leading number out of extra
                    found = _PAGES_RE.search(note)
                    if found:
                        job.page_count = int(found.group(1))
                emit("running", stage, detail, None, 0, 0)
            job.message = detail
            self.index.update(job)

        def gate(note: str) -> None:
            """Pause before speaking until the LLM is out of the way.

            One flow, no second click: while `lms` reports the models, the
            gate re-checks every 5 seconds and continues by itself; when no
            check is possible it waits for the manual Weiter button, and
            after 5 minutes it asks for the "Erneut prüfen" button.
            """
            if job_id in self._cancelled:
                raise _Cancelled()
            event = threading.Event()
            with self._lock:
                self._gates[job_id] = event

            def wait_more() -> bool:
                return event.wait(1.0)

            loaded = loaded_llm_models()
            if loaded == []:
                return  # memory is already free: continue with no pause
            manual = loaded is None
            job.status = "waiting_for_user"
            detail = note if manual else (
                f"LM Studio lädt noch: {', '.join(loaded)} · ich prüfe alle 5 Sekunden"
            )
            job.message = detail
            emit("waiting", "speaking", detail)
            self._log(job, detail)
            self.index.update(job)
            if manual:
                while not wait_more():
                    if job_id in self._cancelled:
                        break
            else:
                polls = 0
                while not wait_more():
                    if job_id in self._cancelled:
                        break
                    polls += 1
                    if polls % 5:
                        continue
                    loaded = loaded_llm_models()
                    if loaded == []:
                        break  # model gone: the flow continues on its own
                    if loaded is None:
                        detail = f"{note} (Prüfen nicht möglich)"
                    elif polls >= 300:
                        detail = (
                            f"LM Studio lädt noch: {', '.join(loaded)}"
                            " · bitte „Erneut prüfen“ drücken"
                        )
                    job.message = detail
                    emit("waiting", "speaking", detail)
                    self.index.update(job)
            with self._lock:
                self._gates.pop(job_id, None)
            if job_id in self._cancelled:
                raise _Cancelled()
            job.message = "weiter"
            self.index.update(job)

        # the mock backend owns no GPU model, so no manual swap gate there
        wait_gate = gate if self.config.tts.backend != "mock" else None

        try:
            folder = self.index.jobs_dir / job_id
            if job.options.get("resume_from") == "speaking":
                language = job.language if job.language in ("de", "en") else "de"
                result = run_speech(
                    folder, self.config, language, progress=progress, gate=wait_gate
                )
            else:
                result = self._run_fn(
                    folder / "source.pdf",
                    self.config,
                    folder,
                    progress=progress,
                    stop_after_script=bool(
                        job.options.get("review", self.config.editor.review_before_tts)
                    ),
                    stop_before_tts=self.config.tts.confirm_before_start,
                    gate=wait_gate,
                    language=str(job.options.get("language", "auto")),
                )
            if job_id in self._cancelled:
                raise _Cancelled()
            meta = result.script.doc_meta or {}
            if meta.get("title"):
                job.title = str(meta["title"])
            if meta.get("page_count"):
                job.page_count = int(meta["page_count"])
            if not job.title:
                job.title = _fallback_title(meta, job.file_name)
            if result.speak.synthesized or result.speak.cached:
                summary = (
                    f"{result.speak.synthesized} Einheiten neu gesprochen, "
                    f"{result.speak.cached} aus dem Zwischenspeicher"
                )
                if result.speak.failed_units:
                    summary += f", {len(result.speak.failed_units)} fehlgeschlagen"
                    self._log(job, f"{_STAGE_LABELS['speaking']}: {summary}", "WARN")
                else:
                    self._log(job, f"{_STAGE_LABELS['speaking']}: {summary}")
            if result.master.ok:
                names = ", ".join(path.name for path in result.master.files)
                self._log(job, f"{_STAGE_LABELS['mastering']}: geschrieben: {names}")
            if result.review_paused:
                job.status = "awaiting_review"
                job.progress = 60
                job.error = ""
                emit("waiting", "script", "Skript wartet auf Prüfung")
            elif result.tts_gate:
                job.status = "awaiting_tts"
                job.progress = 60
                job.error = ""
                job.message = "Bereit für Sprachausgabe"
                emit("waiting", "speaking", "Bereit für Sprachausgabe")
            else:
                job.status = "done" if result.return_code == 0 else "failed"
                job.progress = 100 if result.return_code == 0 else job.progress
                job.error = result.script.error or result.speak.error or result.master.error
                if job.status == "done":
                    job.audio_seconds = int(result.speak.total_seconds)
                    if result.speak.failed_units:
                        job.message = (
                            f"{len(result.speak.failed_units)} von {len(result.speak.units)} "
                            "Einheiten konnten nicht gesprochen werden (Stille eingesetzt)."
                        )
                    else:
                        job.message = "Fertig."
                    emit("done", "mastering", job.message)
                else:
                    failed_stage = str(job.options.get("stage", ""))
                    job.message = f"{_STAGE_LABELS.get(failed_stage, job.status)} fehlgeschlagen."
                    emit("failed", failed_stage, job.message)
            self.index.update(job)
        except _Cancelled:
            job.status = "cancelled"
            job.message = "Abgebrochen."
            emit("failed", str(job.options.get("stage", "")), job.message)
            self._log(job, "abgebrochen")
            self.index.update(job)
        except ModelGuardError as error:
            # the model guard blocked the TTS start: the user must unload the LLM
            job.status = "waiting_for_user"
            job.message = "Bitte das LLM in LM Studio entladen, dann Weiter drücken."
            job.error = str(error)
            emit("waiting", "speaking", job.message)
            self._log(job, f"Modell-Sperre: {error}", "WARN")
            self.index.update(job)
        except Exception as error:  # noqa: BLE001 - a job failure must not kill the thread
            stage_label = _STAGE_LABELS.get(job.status, job.status)
            job.status = "failed"
            job.error = str(error)
            job.error_detail = traceback.format_exc(limit=8).strip()
            job.message = f"{stage_label} fehlgeschlagen."
            emit("failed", str(job.options.get("stage", "")), job.message)
            self._log(job, f"Fehler: {error}", "ERROR")
            self.index.update(job)


def job_folder(index: JobIndex, job_id: str) -> Path:
    return index.jobs_dir / job_id


def save_upload(index: JobIndex, job_id: str, data: bytes, file_name: str) -> dict[str, Any]:
    folder = job_folder(index, job_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "source.pdf").write_bytes(data)
    return {"saved": str(folder / "source.pdf"), "file_name": file_name}
