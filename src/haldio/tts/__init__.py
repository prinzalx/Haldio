"""Speech synthesis backends."""

from haldio.config import TtsConfig
from haldio.tts.base import AudioResult, TTSBackend, TTSParams, Voice
from haldio.tts.mock import MockTTSBackend
from haldio.tts.qwen_local import QwenLocalBackend

__all__ = [
    "AudioResult",
    "MockTTSBackend",
    "QwenLocalBackend",
    "TTSBackend",
    "TTSParams",
    "Voice",
    "create_backend",
]


def create_backend(config: TtsConfig) -> TTSBackend:
    """Build the configured TTS backend."""
    if config.backend == "qwen_local":
        return QwenLocalBackend(config)
    return MockTTSBackend()
