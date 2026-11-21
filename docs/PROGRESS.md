# PROGRESS

## Done — M0 foundation (2026-11-20)

- Repo: `C:\BLOB\output\505`, branch `main`, pushed to https://github.com/prinzalx/Haldio (public).
- Reference repo cloned read-only to `../_reference/ebook2audiobook` (shallow).
- Docs: `BRIEF.md`, `PLAN.md`, `reference-notes.md`, `AGENTS.md`, `README.md`,
  `docs/decisions/0001-new-project.md`, `0002-pymupdf-agpl.md`, `0003-reference-license.md`.
- Skeleton: `pyproject.toml` (uv, hatchling, ruff, pytest), `src/haldio/` with
  `config.py` (config.yaml + defaults) and `cli.py` (`haldio` with stub subcommands),
  `tests/test_config.py`, `config.example.yaml`, `.gitignore`, GitHub Actions CI.
- Verified: `uv sync --extra dev` on Python 3.14.7; 3 tests pass; `ruff check` and
  `ruff format --check` clean; `haldio --version` works.
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
- `inspect_report.py` + CLI `haldio inspect <pdf>` (`--json` writes document.json).
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
- `pipeline/run.py`: full S1→S7 pipeline, `haldio script <pdf> -o <dir>`.
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
- CLI `haldio run <pdf> -o <dir>`: full S1→S9; live check on the synthetic PDF:
  3 chunks -> 19 units synthesized, master stopped with "ffmpeg not found".
- Example `pronunciations.yaml` added; `tts.model` config key added.
- Tests: 50 pass, 1 skip (ffmpeg), mock LLM + MockTTS end to end.

## Done — M4 web (2026-11-20)

- `jobs/worker.py`: FIFO worker thread, cancel between chunks/stages, crashed
  jobs are re-queued on startup; progress callback updates stage + percent.
- Web UI (German, FastAPI + Jinja2 + HTMX): library page with upload and job
  list, job page with 2 s status polling, downloads, cancel, delete.
- `haldio serve` on 127.0.0.1:8505; live smoke test with the real LLM passed
  (job ran S1-S8; only the master stage asked for ffmpeg).
- Tests: 57 pass, 1 skip (ffmpeg).

## Done — M5 polish / release candidate (2026-11-20)

- Review page `/jobs/<id>/review`: script by chunk, warnings highlighted,
  editable text areas, "Weiter zur Sprachausgabe" resumes at S8 (`run_speech`).
- `review_before_tts` config option stops the worker at `awaiting_review` (60%).
- Settings page `/settings`: effective config read-only + "Test LM Studio" and
  "Test TTS" buttons (model list / voice list or a clear error).
- README rewritten: pipeline, install, run, config, tests, eval set.
- Clean-clone test passed: fresh clone -> `uv sync --extra dev` -> 57 tests pass.
- Tests: 61 pass, 1 skip (ffmpeg).

## Release candidate

Tag `v0.1.0-rc1`, GitHub release created. Post-RC: ffmpeg installed, master fixed
(`wave.open` needs `str(path)` on Python 3.14; concat list needs absolute paths)
and verified — real `book.mp3` / `book.ogg` produced. 62 tests pass.

## Correction 1 — TTS runs locally (2026-11-21)

The brief assumed an HTTP TTS server. False: our tool runs Qwen3-TTS itself with
the official `qwen-tts` package in a worker subprocess (`python -m
haldio.tts_worker`), so GPU memory is free when the worker exits.

- `TtsConfig` rewritten (mode, model_id, model_path, worker_python, device,
  dtype, speaker, instruct, reference audio/text, batch_size); hooks are now
  `before_edit` / `after_edit` / `before_speak` / `after_speak` (`lms unload
  --all` verified as a command).
- `QwenLocalBackend` spawns the worker, reads JSON progress lines, terminates
  the worker on cancel. HTTP backend `qwen3.py` removed.
- Worker protocol (units.jsonl in, `<hash>.wav` out, skip existing, progress
  and error lines) tested with a fake worker script: progress, resume, cancel,
  error. 66 tests pass. `live_tts` marker skips real-model tests by default.
- CLI: `haldio tts-pull` (downloads weights once, offline afterwards) and
  `haldio tts-check` (voices + one German test sentence -> tts-check.wav).
  The web "Test TTS" button runs the same worker check.
- Answers from the user: PyTorch build ROCm/HIP (AMD Radeon 8060S, no CUDA),
  first mode `custom_voice`, reference clip later, test language German.

**Checkpoint:** stop after tts-check writes a WAV; the user listens and gives OK.

Result: `haldio tts-check` ran on the real model (ROCm/HIP), printed the nine voices
and ten languages, and wrote `tts-check.wav`. The user found the default voice too
foreign-sounding, listened to one sample per voice, and chose **dylan** (now
`tts.speaker` in `config.yaml`). A longer German test text followed
(`tts-check-dylan.wav`).

## Correction 2 — ready2tts gate (2026-11-20)

RAM is too small for the big LLM and the TTS worker at the same time: the second
worker load while the LLM was running froze the whole machine (power cycle needed),
and no unload command ends the LM Studio model process. Conversion therefore
became a time-shifted process.

- After S7 a web job stops in state `awaiting_tts` (the ready2tts pool).
- The job page shows "Bitte alle anderen lokalen LLM beenden" with an OK button;
  only then stages S8–S9 run.
- Library page: count of ready jobs and "Alle TTS starten" for the whole pool.
- `tts.confirm_before_start` (default on) controls the gate; cancel works on pool
  jobs; batch upload works: prepare many PDFs first, speak them together or singly.
- 68 tests pass, `ruff` clean. See `docs/decisions/0005-ready2tts-gate.md`.

## Known limitations

- ffmpeg is installed on the dev machine (winget, 9.1); other users still install
  it themselves — S9 asks politely if it is missing.
- The big editor LLM and the local TTS worker do not fit into RAM at the same time
  on this machine; the ready2tts gate pauses the job until the user closes the LLM.
- Cancel takes effect between chunks/stages, not mid-request.
- Screenshots in the README need the running UI (skipped in headless tests).

## Next

- Full run with the real model once the user allows TTS again (web pool or `haldio run`).
- Unit-size decision (250 vs 400 chars per TTS unit) after the listening test.
- User feedback on the RC with a real PDF; then 0.1.0 final.

## Open questions

1. **Review-before-speech default.** Off (`review_before_tts: false`), as in the brief.

## Correction 4 (web interface) - section 1 Safety

- Model guard: fixed - the qwencpp backend checks `lms ps --json` before it starts
  tts-server (REST /api/v0/models answered 404 here, the lms CLI was verified); a
  loaded model raises ModelGuardError and the job goes waiting_for_user with
  "Bitte das LLM in LM Studio entladen, dann Weiter drücken.". Every path
  (Weiter-Sprachausgabe, review button, Alle TTS starten, awaiting_tts, Test TTS)
  ends in the backend, so none can skip the guard. No check possible -> manual gate.
- Test TTS: fixed - now POST with the same guard and a warning text by the button.
- Delete: fixed - native `<dialog>` shows the file name, delete runs on POST only.
- Review save: fixed - keeps every field of script.json and rewrites script.md.
- Upload: fixed - accepts only .pdf names with `%PDF-` magic bytes, streamed, stops
  at the size limit.
- HTML escaping: fixed - test results escaped, templates auto-escape.
- CSRF: fixed - Origin/Referer host check on POST (403 for foreign origins).
- htmx: fixed - vendored to `static/vendor/htmx.min.js`, UI works offline.

## Correction 4 - section 2 Worker errors

- Letterless units: fixed - units without letters or digits are merged into the
  previous unit (leading ones dropped) before synthesis.
- Unit failure: fixed - after the 3 retries a unit becomes 500 ms silence, its id
  and text are printed, it is flagged in units.json (`"failed": true`) and listed in
  SpeakResult.failed_units; the job still finishes and the message reports the count.
  A dead tts-server stops the stage with "tts-server crashed". Finished units stay
  in the cache, so "Weiter" continues from the cache (was already true).
- message vs error_detail: fixed - Job gained `error_detail` (traceback, log/API
  only); the UI message is one short German sentence ("Sprachausgabe fehlgeschlagen.").

## Correction 4 - section 3 Missing content

- Upload card: fixed - drag & drop plus file button, chosen name and size shown,
  options language (Automatisch/Deutsch/Englisch) and voice (list from
  `data/voices.json` written by check_qwencpp.py, fallback config speaker — the
  page never starts tts-server), checkbox "Skript vor der Sprachausgabe prüfen",
  button disabled during upload. The server reads exactly the four form fields.
- Job list: fixed - rows show title (from PDF doc_meta), file name, pages, audio
  length, date, German status badge and progress; buttons "Öffnen",
  "Herunterladen" (done only), "Löschen"; newest first; friendly empty text.
- Banner: fixed - "N Jobs warten auf die Sprachausgabe" + "Alle TTS starten" +
  LLM note; the section 1 guard fires in the backend when the server starts.
- Job header: fixed - title, file name, upload date, pages.
- Stepper: fixed - seven stages with icon plus state text (fertig/läuft/
  fehlgeschlagen/offen), never color alone; a failed job stops at the stage the
  worker stored in `job.options["stage"]`.
- Progress and ETA: fixed - bar plus current message; during Sprechen
  "Einheit X von Y" and an ETA measured from this run's finished units only;
  no estimate before the second unit, no hard-coded RTF.
- Summary card: fixed - shows when `02_plan/doc_map.json` exists: summary, main
  topics, language, estimated length (and warnings when present).
- Result card: fixed - `<audio controls>` plus downloads MP3/OGG/Skript/
  QA-Bericht/PDF, only files that exist; download names come from the PDF title
  (`Mein_Buch.mp3`), not the job id.
- Actions by state: fixed - Abbrechen while running; Weiter + Neu starten for
  failed/cancelled; "Skript prüfen" link only when a script exists; Löschen
  with dialog.
- Log: fixed - `<details>` keeps its open/closed state across HTMX swaps
  (localStorage key per job).
- Status labels: fixed - one function `web/labels.py status_label()` maps every
  status id to German label + icon + color class; no raw id in the UI.
- Review page: fixed - original text next to script text (two columns wide,
  stacked narrow), chunk header shows the chapter title, warnings as readable
  text, textareas grow with content, per-chunk HTMX save without page jump and
  with "Gespeichert", filter "Nur Warnungen anzeigen".
- Settings: fixed - read-only table; each test button spins while running and
  shows clear success/error/warn text next to it.

## Correction 4 - section 4 Look and feel

- Theme: fixed - dark default, light via prefers-color-scheme; the top bar
  switch (🌙/☀️) overrides and is remembered in localStorage (try/catch), set
  before first paint. All colors, spacing and radius are CSS variables.
- Design system: fixed - one card, button (primary/secondary/danger), badge,
  stepper, progress, toast, dialog and empty-state style set on the variables.
- Readability: fixed - 16 px base font; light palette chosen for WCAG AA
  contrast; visible :focus-visible outline on every control.
- Icon buttons: fixed - every button carries a text label; the icon-only theme
  switch has an aria-label.
- Responsive: fixed - layouts hold from 360 px, no horizontal scroll; the
  settings table turns into blocks below 640 px; review columns stack.
- Markup: fixed - action rows around forms use <div>, not <p>.
- Toast: fixed - #toast box with aria-live="polite"; HTMX saves announce
  "Gespeichert" politely.
- Polling: fixed - the 2 s poll swaps only the status core; the log <details>
  lives outside the polling div, so it is never swapped while open (open state
  additionally kept in localStorage).
- Page frame: fixed - <title> per page, 🎧 favicon, top bar links to Bücherei
  and Einstellungen.

## Correction 4 - section 5 Tests and finish

- Unit tests: done - model guard with a fake `lms ps` (test_qwencpp/test_web),
  CSRF foreign origin, upload magic-bytes and size limit, review save keeps all
  script.json fields and rewrites script.md, status label function (German label
  for every status id), download list shows only files that exist, silence
  fallback with a fake tts-server. 109 tests pass.
- TestClient page tests: done - library (empty text, title, banner), job page
  (German label, stepper, summary card, result card, log tail), review page and
  per-chunk HTMX save, settings page, all with status code and key German texts.
- Screenshots: done - `scripts/screenshots.py` serves the real app on mock data
  (no TTS model started) and Playwright captures library, running job, finished
  job and review in light AND dark into `docs/screenshots/` (8 PNGs).
- Docs: done - README has a "Web interface" section; playwright added to the dev
  extra.
- Stop: waiting for the owner's OK on the screenshots before any further web work.

## Correction 5 - section 1 One source for the status

- One activity record: fixed - the worker writes ONE record per job through `emit()` (state, stage, done, total, detail, eta, updated_at) into `job.activity`; stepper hint, status block and message read that record.
- Per-item detail in every stage: fixed - editing and verifying count "Abschnitt i von n", speaking counts units, mastering reports "Teil 2 von 3: MP3" (make_master gained a progress callback).
- Time estimate: fixed - ETA only after 5 real items, average of the LAST 10, cache hits and silent units excluded (why "noch ca. 14 min" was too low); wording "noch etwa".
- Sign of life: fixed - spinner only while running; waiting shows grey "Pause - es laeuft nichts"; "zuletzt aktiv vor N s"; running with no update for 60 s shows "Keine Aktivitaet seit N s".
- Long LLM requests: open - elapsed-time fallback only; streaming token count ("das Sprachmodell schreibt seit 38 s (etwa 410 Token)") not done.
- Log = second channel: fixed - box renamed "Technische Details", collapsed, entry counter; one line per real event "HH:MM:SS [LEVEL] Stage: text", no bare stage+percent lines, duplicates logged once; INFO/WARN/ERROR colored; last 200 lines in a scroll box, all lines in `logs/job.log`.
- Log endpoint: fixed - GET /jobs/<id>/log?after=<n> (JSON, polled only while the box is open) + "Protokoll herunterladen" -> /jobs/<id>/log.txt.
- Serve console: fixed - worker logs via the `haldio.worker` stdlib logger; `haldio serve` attaches a StreamHandler with the same text.
- Tests: 115 pass - single-source event, duplicate suppression, 200-line cap, ETA rule with cache exclusion, log endpoint after=, log.txt, activity block.

## Correction 5 - section 2 Buttons, polling, gates

- Polling: fixed - the status block polls every 2 s in EVERY non-final state (incl. awaiting_review, awaiting_tts, waiting_for_user, running); stops only in done/failed/cancelled after one last refresh.
- visibilitychange/pageshow: fixed - base.html JS calls refreshStatus() (htmx trigger 'vis') when the tab becomes visible again.
- Click feedback: fixed - data-busy buttons get disabled + spinner + text "Wird gestartet …"; every action form posts hx-target=#job-status so the response replaces the status block instantly (htmx follows the 303 via GET); data-toast shows the toast; the page never stays unchanged.
- Stepper from one function: fixed - stepper_state(job) in labels.py derives all rows from the job record alone; new "waiting" state (icon pause, word "wartet") for awaiting_review/awaiting_tts/waiting_for_user; failed/cancelled stop at the stage the worker last reported.
- Stepper test table: fixed - test_stepper_state_agrees_with_badge_per_status checks the exact row set for every status id, incl. the new script state; stepper and badge can no longer disagree.
- One gate: fixed - two gates merged into gate(): loaded_llm_models() check; [] = memory free → continue by itself; model loaded → detail "LM Studio lädt noch: X · ich prüfe alle 5 Sekunden" with auto re-check every 5 s, continues automatically when the model is gone; None (check unavailable) → manual "Weiter" only.
- After 5 min: fixed - after 300 polls the detail asks to press "Erneut prüfen"; button label switches between "Weiter" and "Erneut prüfen" by the stored detail.
- Explain unloading: fixed - the awaiting_tts note-box explains eject model / stop server in neutral yellow with numbered steps (red only for errors).
- Pre-speech live checklist: fixed - checklist "Sprachmodell entladen / TTS-Server / Stimme" shown for awaiting_tts, waiting_for_user and speaking with live states.
- Tests: 121 pass - polling attrs per state (parametrized), gate auto-continue with fake guard (["bubo"] → []), manual gate fallback (guard None), stepper table.

## Correction 5 - section 3 Review page

- German intro: fixed - the review page explains what to do and that empty sections are read in their original text.
- Readable headings: fixed - each section shows the chapter path + "Seite N" (page_span start from the chunk input file).
- German reasons: fixed - warning_text maps every editor code to German (unclear_source -> "Quelle schwer lesbar" etc.); a raw code no longer appears in the HTML.
- Empty section: fixed - warning "Für diesen Abschnitt gibt es keinen Hörtext."; every section has an input field (empty ones get one too); buttons "Original übernehmen" (copies the original text) and "Neu erzeugen" (editor LLM, shown only when reachable).
- editor.fallback_to_source: fixed - new config option (default true); synthesize_script reads the ORIGINAL text of empty sections (after the normalizer) and counts them; SpeakResult.empty_sections.
- Log + QA + count: fixed - speaking logs "N Abschnitte ohne Hörtext – es wird der Originaltext vorgelesen."; qa.json/qa_report.html mark "kein Hörtext" and count "ohne Hörtext: N"; the review page header counts "X von Y Abschnitten mit Hinweis".
- Truncated originals: investigated - the stored original (03_edit/chunks/*.in.json) is complete; the truncation was only visual (tiny monospace font + fixed 260px box). Original and script now use the same font and size and wrap long lines.
- Speichern: fixed - the button starts disabled and enables only after a real change in that chunk (JS); after saving it shows "Gespeichert".
- Filter: fixed - clear label "Nur Abschnitte mit Hinweis anzeigen"; empty sections are hidden by it too.
- Job page: fixed - the entry reads "Skript prüfen (optional)" with the hint count ("· 12 Hinweise").
- Tests: 125 pass - empty-section input + buttons, use_original copies text, counter + German reasons + no raw code, fallback in synthesize_script (on and off).

## Correction 5 - section 4 Plain language

- German label table: fixed - UI renames kept the internal ids: extracting=Einlesen, planning=Planen, editing=Hörtext schreiben, verifying=Kontrollieren, script=Skript erstellen, speaking=Vorlesen, mastering=Audio fertigstellen (status badges, stepper and worker log lines all use the new words).
- "Gerade:" box: fixed - under the stepper one box shows the current step's label, a plain explanation and the live detail from the activity record.
- Help table: fixed - <details> "Was bedeuten die Schritte?" with a two-column table (Schritt / was passiert dort) below the stepper.
- Tooltips: fixed - every stepper chip carries title= with its explanation.
- Percent: fixed - the bar now reads "Gesamt 32 %" (job total).
- Tests: 125 pass - existing label assertions updated to the new German words.

## Correction 5 - section 5 Job page layout

- Page count: fixed - `page_count` lands while the stage is still "Einlesen" (the worker parses "N Seiten gelesen" from the progress note at 7 %), no longer only at the end.
- Title fallback: fixed - a PDF without a metadata title gets the first level-1 chapter title, else the file name without extension (`_fallback_title`).
- Deterministic summary: fixed - `quick_summary()` in plan.py builds up to 6 "heading: first paragraph" snippets; `run_script` stores it when the plan stage produced no summary (wired and tested).
- Progress once: fixed - the status block shows ONE bar reading "Gesamt N %"; the old badge in the bar line is gone.
- Action bar: fixed - bottom bar on the card (border-top): Skript pruefen, Zurueck, "Loeschen" far right; Loeschen is not rendered while the job runs.
- Library rows: fixed - two-line rows (title + small meta line) with a right-hand jobside column (badge, thin progress bar, percent, Oeffnen, Loeschen) split by border separators; stacks on narrow screens.
- Danger button: fixed - white text on #b3261e (WCAG AA in both themes); the dead old rule was removed after the review.
- Placeholder: fixed - "Wird erstellt ..." shows in the summary card wherever nothing is computed yet.
- Tests: 130 pass - early page count, title fallback incl. level-1 filter, quick_summary wording and truncation, delete hidden while running, placeholders, doc_map summary wiring.

## Correction 5 - sections 6-8 Look, top bar, settings

- Section 6, calm polished look: done - cards carry a subtle shadow; links show underline only on hover; live buttons brighten on hover (disabled stay calm); progress bars use one accent colour; job rows have a soft hover line; the log box scrolls with a thin scrollbar. Merged a second dead `button:disabled` rule after the review. Correction 6 gap closed 2026-11-21: one spacing scale `--sp-1..--sp-6` (4/8/12/16/24/32 px) now used by main, cards, headings, card-actions and the stepper; title 22 px bold, section titles 16 px, meta text 14 px; the stepper is a vertical list below 640 px; job page order is header -> status block -> summary (own card) -> hints -> "Technische Details" -> action bar. Proof: `test_section6_spacing_and_type_scale`, `test_section6_job_page_order`. Width checks 360/768/1280 come with the section 9 screenshot set.
- Section 7, top bar: partial - the bar sticks to the top while scrolling; the current page is marked in the navigation (`aria-current="page"`, accent colour); job pages mark neither link.
- Section 8, settings page: partial - the effective-config table also shows the data directory ("Daten") and the editor prompt version ("Hörtext-Prompt"); no secrets are rendered (the API key stays out of the page).
- Tests: 133 pass - stylesheet assertions for the polish rules, active-page marking per route, settings rows.
- MISSING (delta check 2026-11-21, see correction-6.md section 1): section 6 done 2026-11-21 (see line above); section 7 dev-text removal and second Buecherei link; section 8 the real editable settings page.

## Correction 5 - section 9 Tests, screenshots, finish

- Tests: 133 pass, ruff clean (src + tests) - the section 1-5 tests are done; the spec-9 tests for top bar and settings are open (built with section 8).
- Screenshots: partial - `scripts/screenshots.py` (temp data dir, mock backend, port 8765 -
  the live `haldio serve` and `data/` were never touched) captured library, running job,
  finished job and review in light AND dark into `docs/screenshots/`; the seed message now
  shows the current wording ("noch etwa").
- README: done - the "Web interface" section describes the correction 5 state (Gerade box,
  Gesamt %, card-bottom actions with Loeschen hidden while running, sticky top bar with
  active-page mark).
- Reviewer: sections 5, 6-8 were each reviewed by the implementation-reviewer subagent;
  all justified change points were applied before the commits.

Stop - waiting for the owner's OK on the screenshots.
