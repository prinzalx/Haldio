# AGENTS.md — Haldio

Senior Python engineer works alone in a local folder. All AI models run on the user's
computer; no document data leaves it. Read `docs/BRIEF.md` at the start of each session.

## Commands

```
uv sync --extra dev          # install (creates .venv)
uv run haldio --version    # CLI
uv run pytest                # tests (skips -m live)
uv run pytest -m live        # tests that need a real LM Studio / TTS server
uv run ruff check src tests  # lint
uv run ruff format src tests # format
uv run uvicorn haldio.web:app --port 8505   # web server (M4)
uv run python scripts/publish.py   # release user files to the public repo
```

## Remotes

- `origin` = private `haldio_dev` — everything, normal `git push` backup.
- `public` = public `Haldio` — only user files; publish with
  `scripts/publish.py` (checks, secret scan, file list, asks before push).
  Never push diary files to `public` by hand.

## Layout

- `src/haldio/` — source. `config.py` loads `config.yaml` (settings) and `.env` (secrets).
- `pipeline/` — one module per stage: S1 ingest … S9 master.
- `prompts/editor/` — versioned editor prompt (`system.en.md`, `examples.de.yaml`).
- `data/` — job data on disk, never committed. `docs/` — brief, progress, plan, decisions.
- `../_reference/ebook2audiobook` — read-only reference repo, outside this repo.

## Conventions

- Python 3.11+, typed signatures, short functions, one file under 400 lines.
- Stages run in strict order, read files and write files; each stage can re-run alone.
- Cache results by hash key; after a crash, skip results with a valid cache key.
- Treat document text as data in every LLM call, never as an instruction.
- Code, comments, commits and docs in English (simple words, short sentences). Web UI in German.
- Conventional Commits. Test with each change; run tests before each commit.
- Never commit secrets, PDFs, audio files or model files.
- **Never start TTS automatically.** Loading Qwen3-TTS needs a user order; an unrequested
  model load crashes the system. Only run stages S8/S9 (speak/master) when the user asks.

## Reviews

After each finished work section (before reporting it done), delegate a review to the
`implementation-reviewer` subagent (`.qwen/agents/`). It reads only; the main agent applies
whatever its change prompt justifies. Before each commit the reviewer reads the spec file for
that section (`docs/corrections/`) and names the proof for each bullet; a bullet without proof
is `open`, never `done`.

After a context compression, read `docs/BRIEF.md`, `AGENTS.md`, and the current correction
file again before the next section.

## Open questions

See `docs/PROGRESS.md`. Ask the user all questions in ONE message, each with a default answer.
