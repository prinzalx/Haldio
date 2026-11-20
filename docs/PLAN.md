# PLAN — architecture and decisions

Status: M0, waiting for the user's OK. Source of requirements: `docs/BRIEF.md`.

## 1. What we build

Upload a technical PDF (15–50 pages) in a local web UI. The tool understands the
document, rewrites the text for the ear with a local LLM, speaks it with a local TTS
model, and hands back an MP3/OGG audiobook. Jobs and results stay on disk and can be
downloaded again later.

Core idea: TTS cannot repair a bad text. Quality comes from the editorial stage, so
that stage gets most of the effort.

## 2. Machine facts (detected, 2026-11-20)

| Item | Value | Consequence |
|---|---|---|
| OS | Windows 11, cmd.exe shell | shell snippets in docs must be cmd-compatible |
| Python | 3.14.7 (`python`, `py -3`) | `requires-python = ">=3.11"` |
| uv | `C:\Users\user\.local\bin\uv.exe` | environment + deps via uv |
| ffmpeg/ffprobe | **not on PATH** | user installs them; path stays configurable |
| git / gh | 2.55.0 / 2.102.0, logged in as `prinzalx` | repo creation via gh |
| Editor LLM | `bubo` at `http://127.0.0.1:8080/v1`, 200k ctx, text+image | LM Studio style, `/v1/models` works |
| TTS | Qwen3-TTS runs **inside our tool** (Correction 1): `qwen-tts` package in a worker subprocess | HTTP adapter removed |
| Web UI port | **8505** | 8080 is taken by the LLM |
| GPU / RAM | AMD Radeon 8060S (Strix Halo, shared VRAM), 31.6 GB RAM | LLM + TTS together froze the machine → ready2tts gate (Correction 2) |

## 3. Pipeline

Stages run in strict order. Each stage reads files and writes files, so any stage can
re-run alone. The hooks `before_edit` / `after_edit` / `before_speak` /
`after_speak` (Correction 1) let the user unload a model
between stages.

| Stage | Output | Notes |
|---|---|---|
| S1 Ingest | `source.pdf`, SHA-256 | magic bytes, title/author/pages, text layer required |
| S2 Extract | `01_extract/document.json` | block model, reading order, footnotes, cross-refs |
| S3 Plan | `02_plan/doc_map.json` | chapter tree, reference index, protected terms, summary |
| S4 Chunk | chunk inputs | structure-first, max 1500 tokens, context per chunk |
| S5 Edit | `03_edit/chunks/*.out.json` | editor LLM, save each result at once |
| S6 Verify | `03_edit/qa.json` | automatic checks + fidelity call, max 2 retries |
| S7 Assemble | `04_script/script.md`, `script.json` | optional `awaiting_review` stop; the ready2tts gate pauses here (Correction 2) |
| S8 Speak | `05_speak/units/*.wav` | Qwen3-TTS worker subprocess, cached by hash |
| S9 Master | `06_output/*` | ffmpeg joins, loudness, MP3/OGG, tags, chapters |

Cache key of an editor result: hash of (input, prompt version, model id, parameters).
Cache key of an audio unit: hash of (text, voice, language, parameters).

## 4. Editorial design

- Editor prompt lives in `prompts/editor/system.en.md`, versioned (`prompt_version`).
- Output is JSON via LM Studio `response_format: json_schema`, with a text-parse fallback.
- Verification is automatic (protected terms, digit strings, length ratio, leftover
  markup, language) plus a second LLM fidelity call at temperature 0.
- A chunk that fails after retries is kept and marked "needs review"; the job continues.
- Two texts: `script_text` (faithful, human readable) and `tts_text` (derived for TTS
  only: numbers to words, speakable identifiers, pronunciation lexicon).

## 5. Code layout

```
src/haldio/
  config.py        # config.yaml + .env, pydantic models
  cli.py           # haldio inspect | script | run | serve
  pipeline/        # s1_ingest.py ... s9_master.py, one module per stage
  extract/         # Extractor interface, PyMuPDF implementation
  llm/             # LM Studio client, editor prompt builder, JSON schema
  tts/             # TTSBackend interface, MockTTSBackend, QwenLocalBackend
  tts_worker.py    # worker subprocess: loads torch + Qwen3-TTS, JSON-line protocol
  audio/           # ffmpeg assembly, normalisation, export
  web/             # FastAPI app, Jinja2 templates, HTMX
  jobs/            # job index on disk, worker queue
prompts/editor/
tests/             # pytest; synthetic PDFs; tests/eval/editor_cases.yaml
```

Rule: every source file stays under 400 lines.

## 6. Decisions taken

1. **New project, not a fork** of ebook2audiobook (see `docs/decisions/0001-new-project.md`).
   Verified in M0 against the clone; see `docs/reference-notes.md`.
2. **License AGPL-3.0-only** for Haldio, chosen by the user. Fits PyMuPDF's AGPL.
3. **Storage on disk**, no database server: `data/jobs/<job_id>/...` plus an index file.
   Nothing is deleted automatically.
4. **Web server binds 127.0.0.1** on port 8505 (brief section 14 wins over the "0.0.0.0"
   line in section 5; the user confirmed a non-8080 port).
5. **CLI framework argparse** for now — no extra dependency until it is really needed.
6. **Package `haldio`, command `haldio`.**

## 7. Risks and open points

- PyMuPDF wheels on Python 3.14: verify at first `uv sync` with the extraction deps (M1).
- Qwen3-TTS runs locally via the `qwen-tts` package (Correction 1). torch is
  not installed in the main environment; the worker uses its own interpreter
  (`tts.worker_python`). Voices and sample rate are read from the model at run
  time, never hard-coded. MockTTS covers the pipeline until the model is pulled.
- ffmpeg is not installed yet; nothing audio-related can run before the user installs it.
- The reference repo study will tell us whether it is modular enough to borrow from.

## 8. Milestones

M0 foundation (this step) → M1 extract → M2 editor → M3 speech → M4 jobs and web UI →
M5 polish. Definition of done per milestone: tests pass, `ruff` clean, `docs/PROGRESS.md`
updated, run instructions work.
