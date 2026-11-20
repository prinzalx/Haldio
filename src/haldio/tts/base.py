"""TTSBackend interface for speech synthesis."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


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

    def healthcheck(self) -> tuple[bool, str]:
        """Return (ok, message) for the settings page."""
        try:
            self.list_voices()
            return (True, "ok")
        except Exception as exc:
            return (False, str(exc))

    def close(self) -> None:  # noqa: B027 - optional override
        """Release any open resources."""
