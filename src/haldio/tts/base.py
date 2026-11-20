"""TTSBackend interface for speech synthesis."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


class ModelGuardError(RuntimeError):
    """An LLM is still loaded in LM Studio; starting TTS would crash the machine."""


@dataclass
class Voice:
    """One available voice."""

    id: str
    language: str = "auto"
    name: str = ""

    def __str__(self) -> str:
        return self.name or self.id


@dataclass
class AudioResult:
    """Raw bytes from TTS plus metadata."""

    data: bytes
    sample_rate: int = 24000
    channels: int = 1
    format: str = "wav"
    duration_seconds: float = 0.0
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class TTSParams:
    """Parameters to pass to one synthesize call."""

    voice: str = ""
    speed: float = 1.0
    seed: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)


class TTSBackend(ABC):
    """Interface for speech synthesis backends."""

    @abstractmethod
    def synthesize(self, text: str, language: str, params: TTSParams) -> AudioResult:
        """Synthesize one text string. The text is already a single TTS unit."""

    @abstractmethod
    def list_voices(self) -> list[Voice]:
        """List all available voices."""

    def synthesize_batch(
        self,
        items: list[tuple[str, Path]],
        language: str,
        params: TTSParams,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[float]:
        """Synthesize all pending (text, target-path) items and write the WAV files.

        Returns one duration in seconds per item. The default loops over
        synthesize(); worker backends override this with a single batch run.
        """
        durations: list[float] = []
        for index, (text, path) in enumerate(items, start=1):
            audio = self.synthesize(text, language, params)
            path.write_bytes(audio.data)
            durations.append(audio.duration_seconds)
            if progress:
                progress(index, len(items))
        return durations

    def cache_variant(self) -> str:
        """Model identification included in the unit cache key (empty = engine only)."""
        return ""

    def healthcheck(self) -> tuple[bool, str]:
        """Return (ok, message) for the settings page."""
        try:
            self.list_voices()
            return (True, "ok")
        except Exception as exc:
            return (False, str(exc))

    def close(self) -> None:  # noqa: B027 - optional override
        """Release any open resources."""
