"""QwenLocalBackend: runs Qwen3-TTS in a worker subprocess.

The worker (``python -m haldio.tts_worker``) loads torch and the model, so
the web server process stays light and GPU memory is freed when the worker
exits. Cancel = terminate: the progress callback may raise, and we kill the
child in that case.
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import wave
from collections.abc import Callable
from pathlib import Path

from haldio.config import TtsConfig
from haldio.tts.base import AudioResult, TTSBackend, TTSParams, Voice

SRC_DIR = Path(__file__).resolve().parents[2]


class QwenLocalBackend(TTSBackend):
    """Load the model once per batch in a worker subprocess (brief 9.1/9.2)."""

    def __init__(
        self,
        config: TtsConfig,
        worker_python: str | None = None,
        worker_args: list[str] | None = None,
    ) -> None:
        self.config = config
        self.worker_python = worker_python or config.worker_python or sys.executable
        self.worker_args = list(worker_args) if worker_args else ["-m", "haldio.tts_worker"]

    def resolve_source(self) -> str:
        """model_path wins, then models/<name> if downloaded, else the HF id."""
        if self.config.model_path:
            return self.config.model_path
        local = Path("models") / self.config.model_id.split("/")[-1]
        return str(local) if local.is_dir() else self.config.model_id

    def model_args(self) -> list[str]:
        c = self.config
        return [
            "--model-id",
            self.resolve_source(),
            "--mode",
            c.mode,
            "--device",
            c.device,
            "--dtype",
            c.dtype,
            "--speaker",
            c.speaker,
            "--instruct",
            c.instruct,
            "--reference-audio",
            c.reference_audio,
            "--reference-text",
            c.reference_text,
            "--batch-size",
            str(c.batch_size),
        ]

    def _spawn(self, args: list[str], offline: bool = True) -> subprocess.Popen:
        env = os.environ.copy()
        env["HF_HUB_OFFLINE"] = "1" if offline else "0"
        env["PYTHONPATH"] = os.pathsep.join([str(SRC_DIR), env.get("PYTHONPATH", "")])
        return subprocess.Popen(
            [self.worker_python, *self.worker_args, *args],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            env=env,
        )

    def synthesize(self, text: str, language: str, params: TTSParams) -> AudioResult:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unit.wav"
            durations = self.synthesize_batch([(text, path)], language, params)
            data = path.read_bytes()
            sample_rate = 24000
            with wave.open(io.BytesIO(data)) as w:
                sample_rate = w.getframerate()
        return AudioResult(data=data, sample_rate=sample_rate, duration_seconds=durations[0])

    def synthesize_batch(
        self,
        items: list[tuple[str, Path]],
        language: str,
        params: TTSParams,
        progress: Callable[[int, int], None] | None = None,
    ) -> list[float]:
        if not items:
            return []
        units_dir = items[0][1].parent
        manifest = units_dir.parent / "units.jsonl"
        lines = [
            json.dumps(
                {"id": i, "text": text, "language": language, "hash": path.stem},
                ensure_ascii=False,
            )
            for i, (text, path) in enumerate(items)
        ]
        manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
        proc = self._spawn(
            ["--units", str(manifest), "--out-dir", str(units_dir), *self.model_args()]
        )
        durations: list[float] = []
        errors: list[str] = []
        assert proc.stdout is not None
        try:
            for raw in proc.stdout:
                line = raw.strip()
                if not line.startswith("{"):
                    continue
                payload = json.loads(line)
                if "done" in payload:
                    if not payload.get("skipped"):
                        durations.append(float(payload.get("seconds", 0.0)))
                    if progress:
                        progress(payload["done"], payload["total"])
                elif "error" in payload:
                    errors.append(str(payload["error"]))
        except BaseException:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
            raise
        return_code = proc.wait()
        if return_code != 0 or errors:
            raise RuntimeError("; ".join(errors) or f"tts worker exited with code {return_code}")
        return durations

    def check(self, text: str, out: Path) -> dict:
        """Worker check mode: load model, report speakers, optionally write a WAV."""
        proc = self._spawn(["--check", *self.model_args(), "--text", text, "--out", str(out)])
        result: dict = {"speakers": [], "languages": [], "wav": ""}
        errors: list[str] = []
        assert proc.stdout is not None
        for raw in proc.stdout:
            line = raw.strip()
            if not line.startswith("{"):
                continue
            payload = json.loads(line)
            if "speakers" in payload:
                result["speakers"] = payload["speakers"]
                result["languages"] = payload.get("languages", [])
            elif "wav" in payload:
                result["wav"] = payload["wav"]
            elif "error" in payload:
                errors.append(str(payload["error"]))
        return_code = proc.wait()
        if return_code != 0 or errors:
            raise RuntimeError("; ".join(errors) or f"tts worker exited with code {return_code}")
        return result

    def pull(self, model_id: str, dest: Path) -> None:
        """Download model weights once (huggingface_hub in the worker env)."""
        proc = self._spawn(["--pull", "--model-id", model_id, "--dest", str(dest)], offline=False)
        assert proc.stdout is not None
        for raw in proc.stdout:
            print(raw, end="")
        return_code = proc.wait()
        if return_code != 0:
            raise RuntimeError(f"tts-pull failed (exit code {return_code})")

    def list_voices(self) -> list[Voice]:
        speakers = self.check("", Path("tts-check.wav"))["speakers"]
        return [Voice(id=str(s), language=self.config.language) for s in speakers]

    def synthesize_unit(self, text: str, language: str, path: Path) -> float:
        """One unit through the batch protocol; returns duration seconds."""
        durations = self.synthesize_batch([(text, path)], language, TTSParams())
        return durations[0] if durations else 0.0
