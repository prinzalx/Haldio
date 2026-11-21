"""Tests for the ONE activity record and the event log the worker writes."""

from __future__ import annotations

from pathlib import Path

from haldio.config import Config
from haldio.jobs import worker as worker_module
from haldio.jobs.index import JobIndex
from haldio.jobs.worker import Worker, _parse_note  # noqa: I001
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


def test_event_log_has_timestamp_level_and_label(tmp_path) -> None:
    index = JobIndex(tmp_path / "data")

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        if progress:
            progress("editing", 30, "1/2 Kapitel 1 #ok")
            progress("speaking", 70, "12/40 #ok")
        return _fake_result(out_dir)

    worker = _inline_worker(index, run_fn)
    job = index.create("book.pdf")
    worker.enqueue(job.id)

    stored = index.get(job.id)
    assert stored is not None and stored.status == "done"
    assert any("[INFO] Hörtext schreiben: Abschnitt 1/2 Kapitel 1" in line for line in stored.logs)
    assert any("[INFO] Umwandeln in Sprache: Einheit 12/40" in line for line in stored.logs)
    disk = (index.jobs_dir / job.id / "logs" / "job.log").read_text(encoding="utf-8")
    assert "Hörtext schreiben: Abschnitt 1/2" in disk


def test_page_count_saved_during_extract_and_title_fallback(tmp_path) -> None:
    """page_count arrives as a structured field at Einlesen time; a PDF
    without title gets the file stem."""
    index = JobIndex(tmp_path / "data")

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        if progress:
            progress("extracting", 7, "12 Seiten gelesen #summary", page_count=12)
        return _fake_result(out_dir)

    job = index.create("book.pdf")
    _inline_worker(index, run_fn).enqueue(job.id)
    stored = index.get(job.id)
    assert stored.page_count == 12
    assert stored.title == "book"


def test_page_count_comes_from_the_field_not_the_note_text(tmp_path) -> None:
    """Text made for people never sets the page count; only the field does."""
    index = JobIndex(tmp_path / "data")

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        if progress:
            progress("extracting", 7, "Alles gelesen #summary")
        return _fake_result(out_dir)

    job = index.create("book.pdf")
    _inline_worker(index, run_fn).enqueue(job.id)
    stored = index.get(job.id)
    assert stored is not None and stored.page_count == 0


def test_title_falls_back_to_first_heading(tmp_path) -> None:
    index = JobIndex(tmp_path / "data")

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        result = _fake_result(out_dir)
        result.script.doc_meta = {"chapters": [{"title": "Kapitel Eins"}]}
        return result

    job = index.create("book.pdf")
    _inline_worker(index, run_fn).enqueue(job.id)
    assert index.get(job.id).title == "Kapitel Eins"


def test_status_block_and_log_show_the_same_event(tmp_path) -> None:
    """The activity record and the log line come from one progress event."""

    index = JobIndex(tmp_path / "data")
    seen: dict[str, str] = {}

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        if progress:
            progress("speaking", 70, "12/40 #ok")
            seen["message"] = index.get(job.id).message
        return _fake_result(out_dir)

    job = index.create("book.pdf")
    worker = _inline_worker(index, run_fn)
    worker.enqueue(job.id)

    stored = index.get(job.id)
    assert any("Einheit 12/40" in line for line in stored.logs)  # log channel
    assert seen["message"] == "Einheit 12 von 40"  # status channel


def test_duplicate_progress_text_is_logged_once(tmp_path) -> None:
    index = JobIndex(tmp_path / "data")

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        if progress:
            for value in (60, 61, 62):
                progress("speaking", value, "5/40 #cache")
        return _fake_result(out_dir)

    worker = _inline_worker(index, run_fn)
    job = index.create("book.pdf")
    worker.enqueue(job.id)

    stored = index.get(job.id)
    repeats = [line for line in stored.logs if "Einheit 5/40" in line]
    assert len(repeats) == 1


def test_progress_log_capped_at_two_hundred(tmp_path) -> None:
    index = JobIndex(tmp_path / "data")

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        if progress:
            for n in range(1, 206):
                progress("speaking", 60, f"{n}/300 #ok")
        return _fake_result(out_dir)

    worker = _inline_worker(index, run_fn)
    job = index.create("book.pdf")
    worker.enqueue(job.id)

    stored = index.get(job.id)
    assert stored is not None
    assert len(stored.logs) == 200
    assert any("Einheit 205/300" in line for line in stored.logs)
    assert not any("Einheit 1/300" in line for line in stored.logs)  # scrolled out
    disk_lines = (
        (index.jobs_dir / job.id / "logs" / "job.log").read_text(encoding="utf-8").splitlines()
    )
    assert len(disk_lines) > 200  # the file keeps every event


def test_eta_rule_five_real_items_and_cache_excluded(tmp_path, monkeypatch) -> None:
    """No estimate before 5 real items; cache hits never enter the average."""
    index = JobIndex(tmp_path / "data")
    ticks = iter(range(0, 10000, 10))
    monkeypatch.setattr(worker_module.time, "monotonic", lambda: float(next(ticks)))

    seen: list[str] = []

    def run_fn(pdf_path, cfg, out_dir, progress=None, **kwargs):
        if progress:
            for note in (
                "1/10 #cache",
                "2/10 #ok",
                "3/10 #ok",
                "4/10 #cache",
                "5/10 #ok",
                "6/10 #ok",
                "7/10 #ok",
                "8/10 #ok",
            ):
                progress("speaking", 60, note)
                seen.append(index.get(job.id).activity.get("detail", ""))
        return _fake_result(out_dir)

    job = index.create("book.pdf")
    worker = _inline_worker(index, run_fn)
    worker.enqueue(job.id)
    # five real deltas of 10 s are reached at event #7 -> ETA for the last 3
    assert "noch etwa" not in seen[5]
    assert seen[6].startswith("Einheit 7 von 10 · noch etwa")


def test_live_note_keeps_the_spec_sentence() -> None:
    """The worker strips a throwaway head word; the spec sentence must survive."""
    done, total, marker, extra = _parse_note(
        "llm das Sprachmodell schreibt seit 38 s (etwa 410 Token)"
    )
    assert (done, total, marker) == (0, 0, "")
    assert extra == "das Sprachmodell schreibt seit 38 s (etwa 410 Token)"
