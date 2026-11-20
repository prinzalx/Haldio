"""Worker protocol tests for QwenLocalBackend with a fake worker script."""

from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

from haldio.config import TtsConfig
from haldio.tts.base import TTSParams
from haldio.tts.qwen_local import QwenLocalBackend

FAKE_WORKER = str(Path("tests") / "fake_tts_worker.py")


def make_backend(monkeypatch, fail: bool = False, sleep: float = 0.0) -> QwenLocalBackend:
    monkeypatch.setenv("FAKE_WORKER_FAIL", "1" if fail else "")
    monkeypatch.setenv("FAKE_SLEEP", str(sleep))
    config = TtsConfig(backend="qwen_local")
    return QwenLocalBackend(config, worker_python=sys.executable, worker_args=[FAKE_WORKER])


def units_dir(tmp_path) -> Path:
    path = tmp_path / "05_speak" / "units"
    path.mkdir(parents=True)
    return path


def test_batch_progress_files_and_durations(tmp_path, monkeypatch) -> None:
    backend = make_backend(monkeypatch)
    units = units_dir(tmp_path)
    items = [("Hallo eins", units / "aaa.wav"), ("Hallo zwei", units / "bbb.wav")]
    seen: list[tuple[int, int]] = []
    durations = backend.synthesize_batch(items, "de", TTSParams(), lambda d, t: seen.append((d, t)))
    assert seen == [(1, 2), (2, 2)]
    assert durations == [0.25, 0.25]
    assert (units / "aaa.wav").read_bytes() == b"RIFFfake"
    assert (units / "bbb.wav").read_bytes() == b"RIFFfake"
    manifest = tmp_path / "05_speak" / "units.jsonl"
    assert manifest.is_file()
    assert manifest.read_text(encoding="utf-8").count("\n") == 2


def test_resume_skips_existing_files(tmp_path, monkeypatch) -> None:
    backend = make_backend(monkeypatch)
    units = units_dir(tmp_path)
    (units / "aaa.wav").write_bytes(b"OLD")
    items = [("Hallo eins", units / "aaa.wav"), ("Hallo zwei", units / "bbb.wav")]
    durations = backend.synthesize_batch(items, "de", TTSParams())
    assert durations == [0.25]  # the skipped unit adds no duration
    assert (units / "aaa.wav").read_bytes() == b"OLD"
    assert (units / "bbb.wav").read_bytes() == b"RIFFfake"


def test_error_line_raises_runtime_error(tmp_path, monkeypatch) -> None:
    backend = make_backend(monkeypatch, fail=True)
    units = units_dir(tmp_path)
    items = [("Hallo eins", units / "aaa.wav"), ("Hallo zwei", units / "bbb.wav")]
    with pytest.raises(RuntimeError, match="fake failure"):
        backend.synthesize_batch(items, "de", TTSParams())


def test_cancel_terminates_worker(tmp_path, monkeypatch) -> None:
    backend = make_backend(monkeypatch, sleep=0.3)
    units = units_dir(tmp_path)
    items = [("Hallo eins", units / "aaa.wav"), ("Hallo zwei", units / "bbb.wav")]

    def cancel_after_first(done: int, total: int) -> None:
        raise RuntimeError("cancel")

    started = time.monotonic()
    with pytest.raises(RuntimeError, match="cancel"):
        backend.synthesize_batch(items, "de", TTSParams(), cancel_after_first)
    assert time.monotonic() - started < 1.0
    assert (units / "aaa.wav").is_file()
    assert not (units / "bbb.wav").is_file()
