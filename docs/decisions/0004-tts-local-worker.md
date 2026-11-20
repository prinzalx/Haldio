# 0004 — TTS runs locally in a worker subprocess (Correction 1)

Date: 2026-11-21. Status: accepted.

The brief assumed LM Studio could serve Qwen3-TTS over HTTP. It cannot: LM
Studio serves the text LLM only. Our tool loads Qwen3-TTS itself with the
official `qwen-tts` package (PyPI, class `Qwen3TTSModel`).

## Decision

- `QwenLocalBackend` starts a worker subprocess (`python -m haldio.tts_worker`)
  instead of loading torch in the web server process. The worker exits at the
  end of the stage and frees GPU memory; a torch/CUDA crash cannot kill the
  web server; cancel kills the worker.
- Heavy dependencies (torch, qwen-tts, soundfile) live in the optional `tts`
  group. CI installs only `dev`, so CI never downloads torch.
- The main venv is Python 3.14; the official package recommends a clean
  Python 3.12 environment. The worker therefore gets its own venv `.venv-tts`
  (Python 3.12) via `tts.worker_python`.
- The machine has no NVIDIA GPU (AMD Radeon 8060S). The user chose the
  ROCm/HIP PyTorch build knowingly; the CPU build is the fallback.
- Protocol: units.jsonl (id, text, language, hash) in, `<hash>.wav` out,
  existing files skipped, one JSON progress line per unit, `error` line plus
  non-zero exit on failure. The stage directory stays `05_speak/` (the brief's
  older text says `05_tts/`; existing jobs and tests use `05_speak/`).
- Hooks per stage: before_edit, after_edit, before_speak, after_speak
  (`before_speak: lms unload --all`). Verified `lms unload` exists.
- Model ids are config values, never hard-coded. The model is looked up as
  `tts.model_path`, then `models/<name>`, then the Hugging Face id. After
  `haldio tts-pull` the worker runs with `HF_HUB_OFFLINE=1`.

## Alternatives considered

- HTTP TTS server (dropped by Correction 1).
- Loading torch inside the web process: keeps GPU memory occupied and ties the
  server to the heavy environment.
