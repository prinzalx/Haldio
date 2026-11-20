"""Stage S8: turn script.json into one audio file per TTS unit, with a cache."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from haldio.config import TtsConfig
from haldio.tts.base import TTSBackend, TTSParams
from haldio.tts.normalizer import make_speakable

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def split_units(text: str, max_chars: int) -> list[str]:
    """Split one block text into TTS units at sentence boundaries."""
    units: list[str] = []
    for sentence in _SENTENCE_END.split(text.strip()):
        if not sentence:
            continue
        while len(sentence) > max_chars:
            cut = sentence.rfind(",", 0, max_chars)
            if cut < max_chars // 2:
                cut = sentence.rfind(" ", 0, max_chars)
            units.append(sentence[:cut].strip())
            sentence = sentence[cut:].strip()
        units.append(sentence)
    return units


def unit_cache_key(text: str, voice: str, backend: str) -> str:
    blob = f"{text}|{voice}|{backend}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


@dataclass
class SpeakResult:
    """Outcome of stage S8."""

    units: list[dict[str, Any]] = field(default_factory=list)
    synthesized: int = 0
    cached: int = 0
    total_seconds: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.units)


def synthesize_script(
    script_data: dict[str, Any],
    backend: TTSBackend,
    backend_name: str,
    tts_config: TtsConfig,
    out_dir: Path,
    language: str,
    pronunciations: dict[str, str] | None = None,
) -> SpeakResult:
    """Synthesize every script block in order; write 05_speak/units.json + WAV files."""
    units_dir = out_dir / "05_speak" / "units"
    units_dir.mkdir(parents=True, exist_ok=True)
    result = SpeakResult()
    params = TTSParams(voice=tts_config.voice)
    for chunk in script_data.get("chunks", []):
        for block in chunk.get("blocks", []):
            spoken = make_speakable(block.get("text", ""), language, pronunciations)
            for piece in split_units(spoken, tts_config.max_chars_per_unit):
                key = unit_cache_key(piece, tts_config.voice, backend_name)
                path = units_dir / f"{key}.wav"
                if path.is_file():
                    result.cached += 1
                    duration = 0.0
                else:
                    audio = backend.synthesize(piece, language, params)
                    path.write_bytes(audio.data)
                    duration = audio.duration_seconds
                    result.synthesized += 1
                result.total_seconds += duration
                result.units.append(
                    {
                        "file": str(path.relative_to(out_dir)),
                        "hash": key,
                        "kind": block.get("kind", "paragraph"),
                        "level": block.get("level"),
                        "text": piece,
                    }
                )
    if not result.units:
        result.error = "no speakable units in script"
        return result
    (out_dir / "05_speak" / "units.json").write_text(
        json.dumps({"units": result.units}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
