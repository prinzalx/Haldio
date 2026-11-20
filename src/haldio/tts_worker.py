"""TTS worker subprocess: loads Qwen3-TTS and speaks pending units.

Protocol (brief section 9.2, Correction 1): input ``--units`` points at a
units.jsonl file (one JSON object per line with id, text, language, hash);
output ``<out-dir>/<hash>.wav``; units whose file exists are skipped. One
JSON line per finished unit on stdout ({"done", "total", "seconds"}), errors
as {"error": ...}. Exit code 0 means success.

Heavy imports (torch, qwen_tts, soundfile) live inside functions so the
module stays importable without the optional ``tts`` dependencies.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
from typing import Any

_LANGUAGE_NAMES = {"de": "German", "en": "English"}


def _emit(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, ensure_ascii=False), flush=True)


def _language_name(code: str) -> str:
    return _LANGUAGE_NAMES.get(code, "Auto")


def _resolve_device(requested: str, torch: Any) -> str:  # noqa: ANN401 - torch module
    if requested != "auto":
        return requested
    return "cuda:0" if torch.cuda.is_available() else "cpu"


def _load_model(args: argparse.Namespace, torch: Any) -> Any:  # noqa: ANN401 - qwen_tts type
    from qwen_tts import Qwen3TTSModel

    kwargs: dict[str, Any] = {}
    if importlib.util.find_spec("flash_attn") is not None:
        kwargs["attn_implementation"] = "flash_attention_2"
    dtype = getattr(torch, args.dtype, torch.bfloat16)
    return Qwen3TTSModel.from_pretrained(
        args.model_id, device_map=args.device, dtype=dtype, **kwargs
    )


def _clone_prompt(model: Any, args: argparse.Namespace) -> Any:  # noqa: ANN401 - qwen_tts type
    if not args.reference_audio:
        raise RuntimeError("clone mode needs tts.reference_audio (a clip of at least 3 seconds)")
    ref_text = args.reference_text or None
    return model.create_voice_clone_prompt(ref_audio=args.reference_audio, ref_text=ref_text)


def _generate(
    model: Any,  # noqa: ANN401 - qwen_tts type
    args: argparse.Namespace,
    prompt: Any,  # noqa: ANN401 - qwen_tts type
    batch: list[dict],
) -> tuple:
    texts = [unit["text"] for unit in batch]
    languages = [_language_name(unit.get("language") or args.language) for unit in batch]
    if args.mode == "clone":
        return model.generate_voice_clone(text=texts, language=languages, voice_clone_prompt=prompt)
    return model.generate_custom_voice(
        text=texts,
        language=languages,
        speaker=[args.speaker] * len(batch),
        instruct=[args.instruct] * len(batch),
    )


def _run_units(model: Any, args: argparse.Namespace, torch: Any) -> int:  # noqa: ANN401
    import soundfile as sf

    units = [
        json.loads(line)
        for line in Path(args.units).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prompt = _clone_prompt(model, args) if args.mode == "clone" else None

    pending = [unit for unit in units if not (out_dir / f"{unit['hash']}.wav").is_file()]
    done = len(units) - len(pending)
    if done:
        _emit({"done": done, "total": len(units), "seconds": 0.0, "skipped": True})

    batch_size = max(1, args.batch_size)
    index = 0
    while index < len(pending):
        batch = pending[index : index + batch_size]
        try:
            wavs, sample_rate = _generate(model, args, prompt, batch)
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            if batch_size == 1:
                raise RuntimeError("CUDA out of memory even with batch size 1") from None
            batch_size = max(1, batch_size // 2)
            continue
        for unit, wav in zip(batch, wavs, strict=False):
            sf.write(out_dir / f"{unit['hash']}.wav", wav, sample_rate)
            done += 1
            _emit({"done": done, "total": len(units), "seconds": len(wav) / float(sample_rate)})
        index += len(batch)
    return 0


def _check(model: Any, args: argparse.Namespace) -> int:  # noqa: ANN401 - qwen_tts type
    import soundfile as sf

    speakers = list(model.get_supported_speakers() or [])
    languages = list(model.get_supported_languages() or [])
    if args.mode == "custom_voice" and not args.speaker and speakers:
        args.speaker = str(speakers[0])
    _emit({"speakers": speakers, "languages": languages, "speaker": args.speaker})
    if args.text:
        prompt = _clone_prompt(model, args) if args.mode == "clone" else None
        wavs, sample_rate = _generate(model, args, prompt, [{"text": args.text, "language": ""}])
        sf.write(args.out, wavs[0], sample_rate)
        _emit({"wav": args.out, "sample_rate": sample_rate})
    return 0


def _pull(args: argparse.Namespace) -> int:
    from huggingface_hub import snapshot_download

    dest = Path(args.dest) if args.dest else Path("models") / args.model_id.split("/")[-1]
    path = snapshot_download(args.model_id, local_dir=str(dest))
    print(f"downloaded {args.model_id} -> {path}", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="haldio.tts_worker")
    parser.add_argument("--units", default="", help="units.jsonl with pending units")
    parser.add_argument("--out-dir", default="", help="directory for <hash>.wav files")
    parser.add_argument("--check", action="store_true", help="report voices, write one test WAV")
    parser.add_argument("--pull", action="store_true", help="download model weights once")
    parser.add_argument("--text", default="", help="check-mode sentence")
    parser.add_argument("--out", default="tts-check.wav", help="check-mode output file")
    parser.add_argument("--model-id", default="")
    parser.add_argument("--mode", default="clone")
    parser.add_argument("--device", default="auto")
    parser.add_argument("--dtype", default="bfloat16")
    parser.add_argument("--language", default="auto")
    parser.add_argument("--speaker", default="")
    parser.add_argument("--instruct", default="")
    parser.add_argument("--reference-audio", default="")
    parser.add_argument("--reference-text", default="")
    parser.add_argument("--batch-size", type=int, default=1)
    args = parser.parse_args(argv)

    try:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        if args.pull:
            return _pull(args)
        import torch

        args.device = _resolve_device(args.device, torch)
        model = _load_model(args, torch)
        if args.check:
            return _check(model, args)
        if not args.units or not args.out_dir:
            raise RuntimeError("batch mode needs --units and --out-dir")
        return _run_units(model, args, torch)
    except Exception as error:  # noqa: BLE001 - report every failure as one protocol line
        _emit({"error": str(error)})
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
