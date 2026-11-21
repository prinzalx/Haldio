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

Open http://127.0.0.1:8505 (German user interface).

## Web interface

- **Bücherei** — upload card with drag & drop: pick or drop several PDFs at once
  (batch), choose language and voice and the "Skript vor der Sprachausgabe prüfen"
  option; every file becomes its own job and the queue prepares them one by one.
  The job list shows title, file, pages, audio length, date, a German status badge
  and progress, newest first. A banner counts jobs waiting in the ready2tts pool
  ("Alle TTS starten").
- **Job page** — a seven-stage stepper (Einlesen → … → Audio fertigstellen) with state text,
  progress bar ("Gesamt N %") and a "Gerade:" box that explains the current step and shows
  the live detail from a single activity record; while the editor LLM writes it reports
  streaming progress ("das Sprachmodell schreibt seit 38 s (etwa 410 Token)"), during
  Vorlesen it counts units ("Einheit 12 von 957") and shows an ETA measured from this
  run's finished units, never a hard-coded factor. While a job waits for the LLM to be
  unloaded the worker re-checks LM Studio every 5 s on its own timer; after 300 s the
  page offers an "Erneut prüfen" button. A summary card appears once the plan exists —
  the planning stage asks the LLM for the real summary (a quick deterministic summary is
  the fallback, marked as such) — and placeholders
  read "Wird erstellt …";
  a result card offers `<audio controls>` and downloads (MP3, OGG, Skript,
  QA-Bericht, PDF — named after the PDF title) for files that exist.
  Actions follow the state: Abbrechen, Weiter, Neu starten, Skript prüfen,
  Löschen (dialog, far right and hidden while the job runs). The log lives in a collapsed
  `<details>` ("Technische Details").
- **Skript prüfen** — original text next to the edited script per chunk (tables and lists
  show their real content, long blocks scroll), chapter
  title in the header, readable warnings, save per chunk with HTMX ("Gespeichert"
  toast), "Original übernehmen" for empty or broken sections and a
  "Nur Abschnitte mit Hinweis anzeigen" filter.
- **Einstellungen** — the full settings page: readable groups with German names, edits
  are validated (bitrate, pauses…), saving writes `data/settings.local.yaml` ("Auf
  Standard zurücksetzen" removes it), the LM Studio card lists models and marks the
  loaded ones, the speaker card lists the nine voices by name and "Hörprobe erzeugen"
  speaks the optional test text ("Testtext für die Hörprobe") in the selected language,
  "Test LM Studio" and "Test TTS"
  show a spinner and a clear result next to the button (TTS respects the model
  guard: the LLM must be unloaded first).
- Light and dark theme (system preference, switchable, remembered). The top bar sticks
  on scroll and marks the current page. No Node.js:
  FastAPI + Jinja2 + a vendored htmx, so the UI works offline.

Screenshots of every page in both themes plus width checks at 360, 768 and 1280 px:
`docs/screenshots/`
(`uv run python scripts/screenshots.py` regenerates them from mock data —
no TTS model is started).

Conversion is time-shifted: stages S1–S7 run with the big editor LLM, then the job
pauses in the **ready2tts** pool. The job page asks you to close all other local LLM
and confirm with OK; only then the TTS worker starts (stages S8–S9). Upload many PDFs
first, let them all be prepared, and start their speech one by one or with
"Alle TTS starten" on the library page. Set `tts.confirm_before_start: false` to run
a job through without the pause.

TTS backends: `qwencpp` (recommended — talks to a local qwentts.cpp `tts-server`
process on port 8111, Vulkan), `mock` (silent test audio, no model needed) and
`qwen_local` (deprecated PyTorch worker, kept as fallback). Set `tts.backend` in
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

AGPL-3.0-only. PyMuPDF, used for PDF extraction, is itself AGPL.
