"""Speech synthesis backends."""

from haldio.tts.base import AudioResult, TTSBackend, TTSParams, Voice
from haldio.tts.mock import MockTTSBackend

__all__ = ["AudioResult", "MockTTSBackend", "TTSBackend", "TTSParams", "Voice"]
