"""Tests for the qwentts.cpp backend (fake HTTP transport, no real server)."""

from __future__ import annotations

import io
import json
import wave
from pathlib import Path

import httpx
import pytest

from haldio.config import TtsConfig
from haldio.tts.base import TTSParams
from haldio.tts.qwencpp import QwenCppBackend, language_name


def _wav_bytes(seconds: float = 1.0, rate: int = 24000) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(b"\x00\x00" * int(rate * seconds))
    return buf.getvalue()


def _backend(handler) -> QwenCppBackend:
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url="http://test")
    return QwenCppBackend(TtsConfig(speaker="dylan"), client=client)


def test_language_name_maps_iso_codes() -> None:
    assert language_name("de") == "german"
    assert language_name("DE") == "german"
    assert language_name("auto") == "auto"
    assert language_name("german") == "german"


def test_synthesize_posts_oai_speech_request() -> None:
    seen: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        return httpx.Response(200, content=_wav_bytes())

    backend = _backend(handler)
    audio = backend.synthesize("Guten Tag.", "de", TTSParams(voice="Dylan"))
    assert audio.data.startswith(b"RIFF")
    assert audio.duration_seconds == 1.0
    assert seen == ["/v1/audio/speech"]


def test_speech_body_uses_lowercase_voice_and_language() -> None:
    bodies: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, content=_wav_bytes())

    backend = _backend(handler)
    backend.synthesize("Hallo.", "de", TTSParams(voice="Dylan"))
    body = bodies[0]
    assert body["input"] == "Hallo."
    assert body["voice"] == "dylan"
    assert body["language"] == "german"
    assert body["response_format"] == "wav"


def test_synthesize_batch_writes_files_and_progress(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=_wav_bytes(seconds=2.0))

    backend = _backend(handler)
    items = [("Ein Text.", tmp_path / "a.wav"), ("Noch ein Text.", tmp_path / "b.wav")]
    calls: list[tuple[int, int, dict]] = []
    durations = backend.synthesize_batch(
        items,
        "de",
        TTSParams(voice="dylan"),
        lambda d, t, info=None: calls.append((d, t, info)),
    )
    assert durations == [2.0, 2.0]
    assert [c[:2] for c in calls] == [(1, 2), (2, 2)]
    assert calls[0][2]["audio"] == 2.0  # per-unit info for the log
    assert (tmp_path / "a.wav").read_bytes().startswith(b"RIFF")
    assert (tmp_path / "b.wav").is_file()


def test_synthesize_batch_retries_empty_generation(tmp_path: Path) -> None:
    state = {"calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["calls"] == 1:
            return httpx.Response(500, text="generation failed")
        return httpx.Response(200, content=_wav_bytes())

    backend = _backend(handler)
    durations = backend.synthesize_batch(
        [("Text.", tmp_path / "u.wav")], "de", TTSParams(voice="dylan")
    )
    assert durations == [1.0]
    assert state["calls"] == 2


def test_failed_unit_becomes_silence_not_job_failure(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="generation failed")

    backend = _backend(handler)
    durations = backend.synthesize_batch(
        [("Text.", tmp_path / "u.wav")], "de", TTSParams(voice="dylan")
    )
    assert durations == [0.5]
    assert backend.failed_units == ["u"]
    assert (tmp_path / "u.wav").stat().st_size > 44


def test_dead_server_stops_the_stage(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="connection refused")

    backend = _backend(handler)

    class DeadProc:
        returncode = 1

        def poll(self) -> int:
            return 1

    backend._proc = DeadProc()  # type: ignore[assignment]
    with pytest.raises(RuntimeError, match="tts-server crashed"):
        backend.synthesize_batch([("Text.", tmp_path / "u.wav")], "de", TTSParams(voice="dylan"))


def test_cache_variant_reports_model_file() -> None:
    config = TtsConfig(backend="qwencpp")
    transport = httpx.MockTransport(lambda r: httpx.Response(200))
    backend = QwenCppBackend(config, client=httpx.Client(transport=transport))
    assert backend.cache_variant() == "qwen-talker-1.7b-customvoice-Q8_0.gguf"
