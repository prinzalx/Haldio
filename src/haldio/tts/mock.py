"""MockTTSBackend: generates silent audio for pipeline testing without real TTS."""

from __future__ import annotations

import io
import math
import struct
import wave

from haldio.tts.base import AudioResult, TTSBackend, TTSParams, Voice

_SAMPLE_RATE = 24000
_CHARS_PER_SECOND = 15.0  # rough speech speed for length estimate


class MockTTSBackend(TTSBackend):
    """Generates a silent WAV tone at a length proportional to text length."""

    def __init__(
        self, sample_rate: int = _SAMPLE_RATE, chars_per_second: float = _CHARS_PER_SECOND
    ) -> None:
        self.sample_rate = sample_rate
        self.chars_per_second = chars_per_second

    def synthesize(self, text: str, language: str, params: TTSParams) -> AudioResult:
        seconds = max(0.5, len(text) / self.chars_per_second)
        n_samples = int(seconds * self.sample_rate)
        # a single low-frequency tone so the audio is not fully silent
        tone_freq = 220.0
        buf = io.BytesIO()
        for i in range(n_samples):
            value = int(8000 * math.sin(2 * math.pi * tone_freq * i / self.sample_rate))
            buf.write(struct.pack("<h", value))
        raw = buf.getvalue()
        wav = io.BytesIO()
        with wave.open(wav, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(self.sample_rate)
            w.writeframes(raw)
        return AudioResult(
            data=wav.getvalue(),
            sample_rate=self.sample_rate,
            channels=1,
            format="wav",
            duration_seconds=seconds,
        )

    def list_voices(self) -> list[Voice]:
        return [
            Voice(id="de-FEM-Marija", language="de", name="Marija"),
            Voice(id="de-MEM-Stephan", language="de", name="Stephan"),
            Voice(id="en-US-Daniel", language="en", name="Daniel"),
        ]

    def healthcheck(self) -> tuple[bool, str]:
        return (True, "mock ok")
