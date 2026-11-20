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

## Done — M1 extract (2026-11-20)

- `pipeline/ingest.py` (S1): SHA-256, magic-byte check, page count, title/author,
  text-layer check with a clear stop message; broken PDF handled.
- `extract/model.py`: `Block`, `CrossReference`, `Document` with `to_dict()` for
  `document.json`.
- `extract/pymupdf_extractor.py` + `extract/extractor.py` (S2): line model, running
  header/footer removal by repetition, page-number removal, column detection by real
  text gap (no line can be lost), heading levels from the PDF outline or font-size
  ranking, table cell grid via `find_tables`, list detection and merging, footnote
  detection by small font near the page bottom, TOC dot-leader detection,
  cross-reference finding in German and English.
- `inspect_report.py` + CLI `hoerbuch inspect <pdf>` (`--json` writes document.json).
- Tests: 23 pass. Synthetic 3-page PDF (`tests/synthetic.py`) with header, footer,
  headings, list, table, two columns, footnote, formula line, cross-references.
- Note: `fitz` is deprecated in PyMuPDF 2.1 — use `import pymupdf`. PyMuPDF has wheels
  for Python 3.14, so no version pin was needed.

## Done — M2 editor (2026-11-20)

- `llm/client.py` (httpx): chat completions, json_schema with text fallback, model list.
- `pipeline/chunk.py` (S4): section-first splitting, max token limit, never inside
  table/code/formula, protected terms and resolved references per chunk.
- `pipeline/editor_output.py`: output schema (blocks + warnings + unresolved refs).
- `pipeline/edit.py` (S5): load prompt, build user message (context + source), parse
  editor result, abbreviation expansion, cache key.
- `pipeline/verify.py` (S6): protected terms check, digits check (warning), length
  ratio warning, leftover markup check.
- `pipeline/assemble.py` (S7): `script.md`, `script.json`, QA report (HTML).
- `pipeline/run.py`: full S1→S7 pipeline, `hoerbuch script <pdf> -o <dir>`.
- Tests: 43 pass; mock client tests; verify tests; chunk tests.

## Next — M3 speech

1. `tts/base.py` (TTSBackend interface), `tts/mock.py` (MockTTSBackend).
2. `tts/normalizer.py` (num2words, identifier speakable, pronunciations.yaml).
3. `pipeline/speak.py` (S8) and `pipeline/master.py` (S9).
4. CLI `hoerbuch run <pdf>`, `QwenTTSBackend` after user confirms Qwen3-TTS setup.

## Open questions

None blocking.

1. **Qwen3-TTS details** (voices, max characters per call, output sample rate). Default:
   I ask again in M3, before writing `QwenTTSBackend`. MockTTS covers the pipeline until then.
2. **Python 3.14 and PyMuPDF wheels.** Default: if no 3.14 wheel exists, I pin the project
   to 3.12 with `uv python pin 3.12`.
3. **Review-before-speech default.** Default: off (`review_before_tts: false`), as in the brief.
