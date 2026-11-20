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
- A local OpenAI-compatible LLM server (editor) and TTS server (speaker)

## Install

```
uv sync --extra dev
copy config.example.yaml config.yaml   # Windows; cp on Linux/macOS
```

Edit `config.yaml`: the LLM URL/model (default `http://127.0.0.1:8080/v1`, model
`bubo`) and the TTS URL (default `http://127.0.0.1:1234/v1`). Secrets go to `.env`.

## Run

```
uv run hoerbuch inspect <pdf>              # show the extracted structure
uv run hoerbuch script <pdf> -o <dir>      # S1-S7: script.md + QA report
uv run hoerbuch run <pdf> -o <dir>         # S1-S9: full audiobook
uv run hoerbuch serve                      # web interface on port 8505
```

Open http://127.0.0.1:8505 (German user interface): upload a PDF, watch the job,
listen to and download the result. The settings page can test both servers.

TTS backends: `mock` (silent test audio, no server needed) and `qwen3`
(OpenAI-compatible `/audio/speech`). Set `tts.backend` in `config.yaml`.

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

## Status

Milestones M0–M5 complete (release candidate). See `docs/PROGRESS.md` for details
and `docs/BRIEF.md` for the full project brief.

## License

AGPL-3.0-only. PyMuPDF, used for PDF extraction, is itself AGPL — see `docs/decisions/`.
