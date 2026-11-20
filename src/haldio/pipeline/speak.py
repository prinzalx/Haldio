"""Stage S8: turn script.json into one audio file per TTS unit, with a cache."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable
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


def unit_cache_key(text: str, voice: str, backend: str, model: str = "") -> str:
    """Cache key over text, voice, backend and model file (name embeds the quant)."""
    blob = f"{text}|{voice}|{backend}|{model}"
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]


def _merge_letterless_units(pieces: list[str]) -> list[str]:
    """Drop units without letters or digits (for example "—" or "•") into the
    previous unit so the TTS engine never sees a symbol-only request."""
    out: list[str] = []
    for piece in pieces:
        if not any(ch.isalnum() for ch in piece):
            if out:
                out[-1] = f"{out[-1]} {piece}".strip()
            continue
        out.append(piece)
    return out


@dataclass
class SpeakResult:
    """Outcome of stage S8."""

    units: list[dict[str, Any]] = field(default_factory=list)
    synthesized: int = 0
    cached: int = 0
    total_seconds: float = 0.0
    failed_units: list[str] = field(default_factory=list)
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
    progress: Callable[[int, int], None] | None = None,
) -> SpeakResult:
    """Synthesize every script block in order; write 05_speak/units.json + WAV files."""
    units_dir = out_dir / "05_speak" / "units"
    units_dir.mkdir(parents=True, exist_ok=True)
    result = SpeakResult()
    params = TTSParams(voice=tts_config.speaker)
    pending: list[tuple[str, Path]] = []
    for chunk in script_data.get("chunks", []):
        for block in chunk.get("blocks", []):
            spoken = make_speakable(block.get("text", ""), language, pronunciations)
            for piece in _merge_letterless_units(
                split_units(spoken, tts_config.max_chars_per_unit)
            ):
                key = unit_cache_key(
                    piece, tts_config.speaker, backend_name, backend.cache_variant()
                )
                path = units_dir / f"{key}.wav"
                result.units.append(
                    {
                        "file": str(path.relative_to(out_dir)),
                        "hash": key,
                        "kind": block.get("kind", "paragraph"),
                        "level": block.get("level"),
                        "text": piece,
                    }
                )
                if path.is_file():
                    result.cached += 1
                else:
                    pending.append((piece, path))
    if not result.units:
        result.error = "no speakable units in script"
        return result
    if pending:
        durations = backend.synthesize_batch(pending, language, params, progress)
        result.synthesized = len(pending)
        result.total_seconds = sum(durations)
        failed = set(getattr(backend, "failed_units", []))
        result.failed_units = sorted(failed)
        for unit in result.units:
            if unit["hash"] in failed:
                unit["failed"] = True
    (out_dir / "05_speak" / "units.json").write_text(
        json.dumps({"units": result.units}, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return result
