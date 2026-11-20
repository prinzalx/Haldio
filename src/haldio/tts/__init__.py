"""Speech synthesis backends."""

from haldio.config import TtsConfig
from haldio.tts.base import AudioResult, TTSBackend, TTSParams, Voice
from haldio.tts.mock import MockTTSBackend
from haldio.tts.qwen_local import QwenLocalBackend
from haldio.tts.qwencpp import QwenCppBackend

__all__ = [
    "AudioResult",
    "MockTTSBackend",
    "QwenCppBackend",
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
    if config.backend == "qwencpp":
        return QwenCppBackend(config)
    return MockTTSBackend()
