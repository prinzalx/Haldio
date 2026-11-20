# PROGRESS

## Done — M0 foundation (2026-11-20)

- Repo: `C:\BLOB\output\505`, branch `main`, pushed to https://github.com/prinzalx/Haldio (public).
- Reference repo cloned read-only to `../_reference/ebook2audiobook` (shallow).
- Docs: `BRIEF.md`, `PLAN.md`, `reference-notes.md`, `AGENTS.md`, `README.md`,
  `docs/decisions/0001-new-project.md`, `0002-pymupdf-agpl.md`, `0003-reference-license.md`.
- Skeleton: `pyproject.toml` (uv, hatchling, ruff, pytest), `src/haldio/` with
  `config.py` (config.yaml + defaults) and `cli.py` (`hoerbuch` with stub subcommands),
  `tests/test_config.py`, `config.example.yaml`, `.gitignore`, GitHub Actions CI.
- Verified: `uv sync --extra dev` on Python 3.14.7; 3 tests pass; `ruff check` and
  `ruff format --check` clean; `hoerbuch --version` works.
- Questions answered by the user: TTS over HTTP, ffmpeg installed by the user,
  repo `prinzalx/Haldio` public, license AGPL-3.0, web port 8505,
  output = source language + MP3 and OGG.

**Waiting for the user's OK on `docs/PLAN.md` and `docs/reference-notes.md`.**

## Next — M1 extract

1. Add `pymupdf` and `pymupdf4llm` (check wheels for Python 3.14 first).
2. S1 Ingest: SHA-256, magic-byte check, title/author/page count, text-layer check.
3. S2 Extract behind an `Extractor` interface: block model in `document.json`,
   header/footer removal by repetition, hyphenation repair, multi-column reading order,
   heading levels from outline plus font size/weight, footnote links, cross-references.
4. CLI `hoerbuch inspect <pdf>` printing outline, block counts, tables, cross-references.
5. Tests with synthetic PDFs generated in the test (reportlab or fpdf2).

## Open questions

None blocking. Small points for later milestones:

1. **Qwen3-TTS details** (voices, max characters per call, output sample rate). Default:
   I ask again in M3, before writing `QwenTTSBackend`. MockTTS covers the pipeline until then.
2. **Python 3.14 and PyMuPDF wheels.** Default: if no 3.14 wheel exists, I pin the project
   to 3.12 with `uv python pin 3.12`.
3. **Review-before-speech default.** Default: off (`review_before_tts: false`), as in the brief.
