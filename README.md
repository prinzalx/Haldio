# Haldio

PDF to audiobook. A local tool: you upload a technical PDF, it becomes an audiobook.

Two AI roles do the work, both on your own computer:

- **Editor** (a local LLM) turns written technical text into a spoken script.
- **Speaker** (a local TTS model) reads that script aloud.

Document data does not leave your machine.

## Install

```
uv sync --extra dev
copy config.example.yaml config.yaml
```

`ffmpeg` and `ffprobe` must be on the PATH.

## Run

```
uv run hoerbuch inspect <pdf>
uv run hoerbuch serve
```

Open http://127.0.0.1:8505 (German user interface).

## Test and lint

```
uv run pytest
uv run ruff check src tests
```

## Status

Milestone M0 (foundation). See `docs/PROGRESS.md` and `docs/BRIEF.md`.

## License

AGPL-3.0-only. PyMuPDF, used for PDF extraction, is itself AGPL — see `docs/decisions/`.
