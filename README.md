# Haldio

PDF to audiobook. A local tool: you put in a technical PDF, you get an audiobook.

Two AI roles do the work, both on your own computer:

- **Editor** (a local LLM) turns written technical text into a spoken script.
- **Speaker** (a local TTS model) reads that script aloud.

Document data does not leave your machine.

## What it does

1. **Ingest** — checks the PDF and hashes it.
2. **Extract** — reads structure with PyMuPDF: headings, paragraphs, tables, lists,
   footnotes, two-column pages, running headers.
3. **Plan** — chapter tree, protected terms, cross-reference index, time estimate.
4. **Chunk** — splits the document into editor-sized chunks (never inside a table).
5. **Edit** — the LLM rewrites each chunk as spoken language (JSON out).
6. **Verify** — checks protected terms, leftover markup, length; retries with feedback.
7. **Assemble** — `script.md` + `script.json` + an HTML QA report.
8. **Speak** — the TTS model records one audio file per unit, cached by hash.
9. **Master** — ffmpeg merges everything into MP3 and OGG with natural pauses.

## Requirements

- [uv](https://docs.astral.sh/uv/) and Python 3.11+
- `ffmpeg` and `ffprobe` on the PATH (for stage S9)
- A local OpenAI-compatible LLM server (editor). The speaker (Qwen3-TTS) runs
  inside this tool — see "TTS setup".

## Install

```
uv sync --extra dev
copy config.example.yaml config.yaml   # Windows; cp on Linux/macOS
```

Edit `config.yaml`: the LLM URL/model (default `http://127.0.0.1:8080/v1`, model
`bubo`) and the TTS settings (see "TTS setup"). Secrets go to `.env`.

## Run

```
uv run haldio inspect <pdf>              # show the extracted structure
uv run haldio script <pdf> -o <dir>      # S1-S7: script.md + QA report
uv run haldio run <pdf> -o <dir>         # S1-S9: full audiobook
uv run haldio serve                      # web interface on port 8505
```

Open http://127.0.0.1:8505 (German user interface): upload a PDF, watch the job,
listen to and download the result. The settings page can test both servers.

Conversion is time-shifted: stages S1–S7 run with the big editor LLM, then the job
pauses in the **ready2tts** pool. The job page asks you to close all other local LLM
and confirm with OK; only then the TTS worker starts (stages S8–S9). Upload many PDFs
first, let them all be prepared, and start their speech one by one or with
"Alle TTS starten" on the library page. Set `tts.confirm_before_start: false` to run
a job through without the pause.

TTS backends: `mock` (silent test audio, no model needed) and `qwen_local`
(the tool runs Qwen3-TTS itself in a worker subprocess). Set `tts.backend` in
`config.yaml`.

## TTS setup

```
uv venv .venv-tts --python 3.12
.venv-tts\Scripts\pip install torch torchaudio --no-index --find-links https://repo.radeon.com/rocm/windows/rocm-rel-7.2.1/
.venv-tts\Scripts\pip install "qwen-tts>=0.1" soundfile huggingface_hub
```

The ROCm wheels above fit AMD GPUs on Windows. On NVIDIA use the PyTorch CUDA index
(`--index-url https://download.pytorch.org/whl/cu128`); on a CPU-only machine plain
`pip install torch torchaudio`.

In `config.yaml` set `tts.backend: qwen_local`, the chosen `tts.model_id`
(for example `Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice`), `tts.mode`, and
`tts.worker_python: .venv-tts\Scripts\python.exe`. Then:

```
uv run haldio tts-pull    # download the model weights once (Hugging Face)
uv run haldio tts-check   # load the model, print voices, write tts-check.wav
```

After `tts-pull` the worker runs offline (`HF_HUB_OFFLINE=1`). Mode `clone`
(Base model) needs a reference clip of at least 3 seconds in `voices/`; mode
`custom_voice` (CustomVoice model) uses preset voices. The web settings page
has the same check behind the "Test TTS" button. The TTS worker needs the memory
the editor LLM used, so close the LLM before stage S8 — the ready2tts gate
(see "Run") does this for you.

## Test and lint

```
uv run pytest                # unit tests (mocked servers)
uv run pytest -m live        # tests that need a real LM Studio / TTS server
uv run ruff check src tests
```

The editor prompt has its own eval set:

```
uv run python scripts/eval_editor.py
```

## License

AGPL-3.0-only. PyMuPDF, used for PDF extraction, is itself AGPL — see `docs/decisions/`.
