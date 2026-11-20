"""Speech synthesis backends."""

from haldio.config import TtsConfig
from haldio.tts.base import AudioResult, TTSBackend, TTSParams, Voice
from haldio.tts.mock import MockTTSBackend
from haldio.tts.qwen3 import QwenTTSBackend

__all__ = [
    "AudioResult",
    "MockTTSBackend",
    "QwenTTSBackend",
    "TTSBackend",
    "TTSParams",
    "Voice",
    "create_backend",
]


def create_backend(config: TtsConfig) -> TTSBackend:
    """Build the configured TTS backend."""
    if config.backend == "qwen3":
        return QwenTTSBackend(config)
    return MockTTSBackend()
