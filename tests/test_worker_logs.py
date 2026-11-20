"""Tests for the per-job progress log kept on the job record."""

from __future__ import annotations

from pathlib import Path

from haldio.config import Config
from haldio.jobs.index import JobIndex
from haldio.jobs.worker import Worker
from haldio.pipeline.master import MasterResult
from haldio.pipeline.run import BookResult, ScriptResult
from haldio.pipeline.speak import SpeakResult


def _fake_result(out_dir: Path) -> BookResult:
    master_file = out_dir / "06_master" / "book.mp3"
    master_file.parent.mkdir(parents=True, exist_ok=True)
    master_file.write_bytes(b"ID3fake")
    return BookResult(
        script=ScriptResult(out_dir=out_dir, chunks=2),
        speak=SpeakResult(units=[{"file": "x"}], synthesized=3, total_seconds=42.0),
        master=MasterResult(files=[master_file]),
    )


def _inline_worker(index: JobIndex, run_fn) -> Worker:
    config = Config()
    worker = Worker(index, config, run_fn=run_fn, inline=True)
    worker.start()
    return worker


def test_job_record_keeps_progress_log(tmp_path) -> None:
    index = JobIndex(tmp_path / "data")

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        if progress:
            progress("editing", 30, "Kapitel 1")
            progress("speaking", 70, "12/40")
        return _fake_result(out_dir)

    worker = _inline_worker(index, run_fn)
    job = index.create("book.pdf")
    worker.enqueue(job.id)

    stored = index.get(job.id)
    assert stored is not None and stored.status == "done"
    assert any("editing 30% Kapitel 1" in line for line in stored.logs)
    assert any("speaking 70% 12/40" in line for line in stored.logs)
    disk = (index.jobs_dir / job.id / "worker.log").read_text(encoding="utf-8")
    assert "editing 30% Kapitel 1" in disk


def test_progress_log_capped_at_thirty(tmp_path) -> None:
    index = JobIndex(tmp_path / "data")

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        if progress:
            for n in range(1, 36):
                progress("speaking", 60, f"unit {n}")
        return _fake_result(out_dir)

    worker = _inline_worker(index, run_fn)
    job = index.create("book.pdf")
    worker.enqueue(job.id)

    stored = index.get(job.id)
    assert stored is not None
    assert len(stored.logs) == 30
    assert stored.logs[-1].endswith("unit 35")
    assert all(not line.endswith("unit 1") for line in stored.logs)
    disk = (index.jobs_dir / job.id / "worker.log").read_text(encoding="utf-8")
    assert len(disk.strip().splitlines()) == 35
