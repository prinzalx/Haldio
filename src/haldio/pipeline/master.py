"""Stage S9: merge unit audio into the final audiobook files with ffmpeg."""

from __future__ import annotations

import json
import shutil
import struct
import subprocess
import wave
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class MasterResult:
    """Outcome of stage S9: the merged master files."""

    files: list[Path] = field(default_factory=list)
    duration_seconds: float = 0.0
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and bool(self.files)


def _silence_wav(path: Path, milliseconds: int, sample_rate: int) -> Path:
    """Write a silent mono 16-bit WAV of the given length."""
    n = int(sample_rate * milliseconds / 1000)
    with path.open("wb") as handle, wave.open(handle, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(struct.pack(f"<{n}h", *([0] * n)))
    return path


def _pause_for(unit: dict[str, Any], pause_ms: dict[str, int]) -> int:
    """Pause inserted BEFORE this unit, by its kind."""
    if unit.get("kind") == "heading":
        return int(pause_ms.get("chapter" if int(unit.get("level") or 1) <= 1 else "heading", 900))
    return int(pause_ms.get("paragraph", 500))


def _ffmpeg_concat(unit_paths: list[Path], merged: Path) -> None:
    list_file = merged.with_name("concat.txt")
    lines = "".join(f"file '{p.resolve().as_posix()}'\n" for p in unit_paths)
    list_file.write_text(lines, encoding="utf-8")
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(list_file),
            "-c",
            "copy",
            str(merged),
        ],
        check=True,
    )


def _ffmpeg_encode(merged: Path, target: Path, audio_format: str, bitrate_kbps: int) -> None:
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(merged)]
    if audio_format == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", f"{bitrate_kbps}k"]
    elif audio_format in ("ogg", "oga"):
        cmd += ["-c:a", "libvorbis", "-q:a", "5"]
    elif audio_format == "m4b":
        cmd += ["-c:a", "aac", "-b:a", f"{bitrate_kbps}k"]
    cmd += [str(target)]
    subprocess.run(cmd, check=True)


def make_master(
    out_dir: Path,
    formats: list[str],
    pause_ms: dict[str, int],
    bitrate_kbps: int = 96,
    sample_rate: int = 24000,
    progress: Callable[[int, int, str], None] | None = None,
) -> MasterResult:
    """Merge 05_speak/units.json audio into 06_master/book.<format> files."""
    if shutil.which("ffmpeg") is None:
        return MasterResult(error="ffmpeg not found - please install ffmpeg")
    units_file = out_dir / "05_speak" / "units.json"
    if not units_file.is_file():
        return MasterResult(error="missing 05_speak/units.json - run stage S8 first")
    units: list[dict[str, Any]] = json.loads(units_file.read_text(encoding="utf-8"))["units"]
    if not units:
        return MasterResult(error="no audio units to merge")

    master_dir = out_dir / "06_master"
    master_dir.mkdir(parents=True, exist_ok=True)
    silence_dir = out_dir / "05_speak" / "silence"
    silence_dir.mkdir(parents=True, exist_ok=True)

    ordered: list[Path] = []
    for index, unit in enumerate(units):
        if index > 0:
            pause = _pause_for(unit, pause_ms)
            if pause > 0:
                ordered.append(_silence_wav(silence_dir / f"pause_{pause}.wav", pause, sample_rate))
        ordered.append(out_dir / unit["file"])

    merged = master_dir / "merged.wav"
    try:
        _ffmpeg_concat(ordered, merged)
    except subprocess.CalledProcessError as error:
        return MasterResult(error=f"ffmpeg concat failed: {error}")

    result = MasterResult()
    for index, audio_format in enumerate(formats, start=1):
        target = master_dir / f"book.{audio_format}"
        try:
            _ffmpeg_encode(merged, target, audio_format, bitrate_kbps)
            result.files.append(target)
            if progress:
                progress(index, len(formats), audio_format.upper())
        except subprocess.CalledProcessError as error:
            result.error = f"ffmpeg encode {audio_format} failed: {error}"
            return result
    return result
