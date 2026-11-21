"""qwencpp backend: talks to a local qwentts.cpp tts-server (Vulkan).

One server process serves the whole speak stage; each unit is one POST
/v1/audio/speech request with response_format wav. The server loads the
talker GGUF on startup, so starting it can take a while.
"""

from __future__ import annotations

import io
import json
import subprocess
import tempfile
import time
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from haldio.config import TtsConfig
from haldio.llm.client import loaded_llm_models
from haldio.tts.base import AudioResult, ModelGuardError, TTSBackend, TTSParams, Voice

# The server wants the upstream qwen3-tts language names ("german", ...).
_LANG_NAMES = {
    "auto": "auto",
    "de": "german",
    "en": "english",
    "es": "spanish",
    "fr": "french",
    "it": "italian",
    "pt": "portuguese",
    "pl": "polish",
    "tr": "turkish",
    "ru": "russian",
    "zh": "chinese",
    "ja": "japanese",
    "ko": "korean",
}

_MAX_ATTEMPTS = 3
_SILENCE_SECONDS = 0.5
_SAMPLE_RATE = 24000


def language_name(code: str) -> str:
    """Map an ISO code to the upstream language name; unknown codes pass through."""
    return _LANG_NAMES.get(code.strip().lower(), code)


class QwenCppBackend(TTSBackend):
    """Speech synthesis through a qwentts.cpp tts-server HTTP process."""

    def __init__(self, config: TtsConfig, client: httpx.Client | None = None) -> None:
        self._config = config
        self._client = client
        self._proc: subprocess.Popen[bytes] | None = None
        self._log = None
        self.failed_units: list[str] = []

    # -- server lifecycle -------------------------------------------------

    def _server_path(self) -> Path:
        return Path(self._config.qwencpp_server)

    def _base_url(self) -> str:
        return f"http://127.0.0.1:{self._config.qwencpp_port}"

    def _ensure_server(self) -> None:
        """Start tts-server once and wait until /health answers."""
        if self._client is not None:
            return
        loaded = loaded_llm_models()
        if loaded:
            raise ModelGuardError(f"LM Studio lädt noch: {', '.join(loaded)}")
        binary = self._server_path()
        if not binary.is_file():
            raise RuntimeError(f"tts-server not found: {binary} - build qwentts.cpp first")
        args = [
            str(binary),
            "--model",
            self._config.qwencpp_model,
            "--codec",
            self._config.qwencpp_codec,
            "--host",
            "127.0.0.1",
            "--port",
            str(self._config.qwencpp_port),
        ]
        if self._config.qwencpp_device:
            args += ["--device", self._config.qwencpp_device]
        log = open(Path(tempfile.gettempdir()) / "qwentts-server.log", "wb")  # noqa: SIM115 - held by child
        self._proc = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)  # noqa: S603
        self._log = log
        timeout = httpx.Timeout(600.0, connect=10.0)
        self._client = httpx.Client(base_url=self._base_url(), timeout=timeout)
        deadline = time.monotonic() + self._config.qwencpp_startup_timeout
        while time.monotonic() < deadline:
            if self._proc.poll() is not None:
                raise RuntimeError(f"tts-server exited ({self._proc.returncode}) during startup")
            try:
                if self._client.get("/health").status_code == 200:
                    return
            except httpx.HTTPError:
                pass
            time.sleep(1.0)
        self.close()
        raise RuntimeError("tts-server not healthy in time (see %TEMP%\\qwentts-server.log)")

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None
        if self._proc is not None:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                self._proc.kill()
            self._proc = None
        if self._log is not None:
            self._log.close()
            self._log = None

    # -- synthesis ---------------------------------------------------------

    def synthesize(self, text: str, language: str, params: TTSParams) -> AudioResult:
        self._ensure_server()
        assert self._client is not None
        body = {
            "input": text,
            "voice": (params.voice or self._config.speaker).lower(),
            "language": language_name(language),
            "response_format": "wav",
        }
        response = self._client.post("/v1/audio/speech", json=body)
        if response.status_code != 200:
            raise RuntimeError(f"tts-server HTTP {response.status_code}: {response.text[:200]}")
        data = response.content
        if len(data) < 1000:
            raise RuntimeError("tts-server returned an empty audio result")
        return AudioResult(data=data, duration_seconds=_wav_duration(data))

    def synthesize_batch(
        self,
        items: list[tuple[str, Path]],
        language: str,
        params: TTSParams,
        progress: Callable[..., None] | None = None,
    ) -> list[float]:
        """Synthesize all items against one server; retry empty generations.

        A unit that still fails after the retries becomes 500 ms of silence
        and is listed in self.failed_units; a dead server stops the stage.
        """
        self._ensure_server()
        self.failed_units = []
        durations: list[float] = []
        for index, (text, path) in enumerate(items, start=1):
            started = time.monotonic()
            info: dict[str, Any] = {}
            for attempt in range(1, _MAX_ATTEMPTS + 1):
                try:
                    audio = self.synthesize(text, language, params)
                except RuntimeError as error:
                    if self._proc is not None and self._proc.poll() is not None:
                        raise RuntimeError(f"tts-server crashed: {error}") from error
                    if attempt == _MAX_ATTEMPTS:
                        print(f"unit {path.stem} failed: {error} | text: {text[:60]}")
                        self.failed_units.append(path.stem)
                        path.write_bytes(_silence_wav())
                        durations.append(_SILENCE_SECONDS)
                        info = {"fail": True}
                    continue
                path.write_bytes(audio.data)
                durations.append(audio.duration_seconds)
                info = {"audio": audio.duration_seconds, "took": time.monotonic() - started}
                break
            if progress:
                progress(index, len(items), info)
        return durations

    def list_voices(self) -> list[Voice]:
        self._ensure_server()
        assert self._client is not None
        response = self._client.get("/v1/audio/voices")
        response.raise_for_status()
        payload = response.json()
        voices = payload.get("voices", []) if isinstance(payload, dict) else []
        return [Voice(id=str(name), language="auto") for name in voices]

    def cache_variant(self) -> str:
        """Model identification for the unit cache key (file name embeds the quant)."""
        return Path(self._config.qwencpp_model).name


def _silence_wav() -> bytes:
    """A short mono 16-bit silence used when one unit fails for good."""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(_SAMPLE_RATE)
        handle.writeframes(b"\x00\x00" * int(_SAMPLE_RATE * _SILENCE_SECONDS))
    return buf.getvalue()


def _wav_duration(data: bytes) -> float:
    """Duration in seconds read from the WAV header; 0.0 when unreadable."""
    try:
        with wave.open(io.BytesIO(data), "rb") as handle:
            return handle.getnframes() / float(handle.getframerate())
    except Exception:  # noqa: BLE001 - duration is informational only
        return 0.0


def server_config_summary(config: TtsConfig) -> str:
    """One-line summary of the effective server setup (for logs)."""
    return json.dumps(
        {
            "server": config.qwencpp_server,
            "model": Path(config.qwencpp_model).name,
            "codec": Path(config.qwencpp_codec).name,
            "port": config.qwencpp_port,
        },
        ensure_ascii=False,
    )
