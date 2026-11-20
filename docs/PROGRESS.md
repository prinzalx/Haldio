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
- Eval set: `tests/eval/editor_cases.yaml` (15 cases) + `scripts/eval_editor.py`
  (runs the cases against the live LM Studio, prints pass/fail per rule).
- Live-run hardening: `parse_editor_result` rejects a JSON object without a
  "blocks" key (Pydantic defaults had hidden a wrong-shaped `{"script": ...}`
  answer as valid-but-empty); an empty `blocks` array triggers the retry loop;
  few-shot examples are appended to the system prompt so the model keeps the
  JSON shape and the decimal commas.
- Column fix: the gutter is now computed from narrow (column-width) lines only,
  and full-width lines end a column zone — a heading above two columns no
  longer hid the gap and y-sorted the column lines into each other.
- Tests: 41 pass; mock client tests; verify tests; chunk tests; retry tests.

## Done — M3 speech (2026-11-20)

- `tts/normalizer.py`: pronunciations.yaml replacements, decimal comma ->
  "Komma", standalone numbers -> words (num2words), CamelCase identifiers split.
- `pipeline/speak.py` (S8): script blocks -> sentence-sized TTS units, one WAV per
  unit under `05_speak/units/`, cache by hash(text, voice, backend), `units.json`.
- `pipeline/master.py` (S9): ffmpeg concat with pause silences (paragraph/heading/
  chapter) and per-format encode to `06_master/book.<fmt>`; clear error when
  ffmpeg is missing (user installs it).
- `tts/qwen3.py` (QwenTTSBackend): OpenAI-compatible POST /audio/speech; voices
  from GET /audio/voices. Server not up yet — defaults from config, verify when
  the user starts the TTS server.
- CLI `hoerbuch run <pdf> -o <dir>`: full S1→S9; live check on the synthetic PDF:
  3 chunks -> 19 units synthesized, master stopped with "ffmpeg not found".
- Example `pronunciations.yaml` added; `tts.model` config key added.
- Tests: 50 pass, 1 skip (ffmpeg), mock LLM + MockTTS end to end.

## Next — M4 web

1. Job index (`jobs/index.py` exists) + worker thread (resume, cancel, FIFO).
2. Web UI in German: library page, job page with stages and downloads, delete.
3. `hoerbuch serve`, Jinja2 + HTMX on port 8505.

## Open questions

None blocking.

1. **Qwen3-TTS details** (voices, max characters per call, output sample rate). Default:
   I ask again in M3, before writing `QwenTTSBackend`. MockTTS covers the pipeline until then.
2. **Python 3.14 and PyMuPDF wheels.** Default: if no 3.14 wheel exists, I pin the project
   to 3.12 with `uv python pin 3.12`.
3. **Review-before-speech default.** Default: off (`review_before_tts: false`), as in the brief.
