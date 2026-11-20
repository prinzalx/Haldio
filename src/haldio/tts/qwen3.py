"""Qwen3-TTS backend over an OpenAI-compatible HTTP endpoint (LM Studio)."""

from __future__ import annotations

import io
import wave

import httpx

from haldio.config import TtsConfig
from haldio.tts.base import AudioResult, TTSBackend, TTSParams, Voice


class QwenTTSBackend(TTSBackend):
    """Calls POST {base_url}/audio/speech; voices from GET {base_url}/audio/voices."""

    def __init__(self, config: TtsConfig, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
        self._client = httpx.Client(
            base_url=config.base_url,
            headers=headers,
            timeout=httpx.Timeout(300.0),
            transport=transport,
        )

    def synthesize(self, text: str, language: str, params: TTSParams) -> AudioResult:
        payload = {
            "model": self.config.model,
            "input": text,
            "voice": params.voice or self.config.voice,
            "response_format": "wav",
        }
        response = self._client.post("/audio/speech", json=payload)
        response.raise_for_status()
        data = response.content
        duration = 0.0
        sample_rate = 24000
        try:
            with wave.open(io.BytesIO(data)) as w:
                sample_rate = w.getframerate()
                duration = w.getnframes() / float(sample_rate or 1)
        except Exception:
            pass
        return AudioResult(
            data=data, sample_rate=sample_rate, format="wav", duration_seconds=duration
        )

    def list_voices(self) -> list[Voice]:
        response = self._client.get("/audio/voices")
        response.raise_for_status()
        body = response.json()
        voices = body.get("data", body) if isinstance(body, dict) else body
        out: list[Voice] = []
        for item in voices:
            if isinstance(item, str):
                out.append(Voice(id=item, language=self.config.language))
            elif isinstance(item, dict):
                out.append(
                    Voice(
                        id=str(item.get("id", item.get("voice", ""))),
                        language=str(item.get("language", self.config.language)),
                        name=str(item.get("name", "")),
                    )
                )
        return out

    def close(self) -> None:
        self._client.close()
