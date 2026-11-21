# Correction 6: close the gaps (this message is the confirmation to go)

Your delta check was honest and useful. Thank you. The answer to your question is: **yes, close the gaps now, in the order 6, 7, 8, 9.**

About your stop: I accept your reason. It was no technical block. My earlier text said "Stop and wait for my OK", and my last message asked only for a check. This message is the confirmation. **Do not stop between the sections.** Stop only once, at the end of section 3 of this message.

## 0. Process rules (they fix the cause of the gaps)

1. **Keep the specification in the repo.** Save the text of each correction as it is in your context to `docs/corrections/correction-1.md` … `correction-5.md`, and this message as `correction-6.md`. If a part is missing because of the context compression, tell me which part. I will send it again. Add this rule to `AGENTS.md`: "After a context compression, read `docs/BRIEF.md`, `AGENTS.md`, and the current correction file again before the next section."
2. **Honest status in `PROGRESS.md`.** Track each bullet of the spec with one of three states: `done` (add the proof: test name or file), `partial` (say what is missing), `open`. Never write `done` for a bullet that you built in a lighter form. Correct these entries now: "Correction 5 – sections 6-8" and "section 9" say `done`, but your delta check says `partial`.
3. **The reviewer checks against the spec, not only against the diff.** Before each commit, the implementation-reviewer subagent reads the spec file for that section. Its report quotes each bullet and names the proof. A bullet without proof is `open`. In the last round the reviewer approved sections 6 to 8 although they were incomplete. Change the reviewer's task so that this cannot happen again.
4. Keep the rules of Correction 5, section 0: no model start, do not touch `data/`, tests green, `ruff` clean, one commit for each section.

## 1. Gaps from your delta check (do all of them)

- **Section 6 (look).** Spacing scale as CSS variables (4, 8, 12, 16, 24, 32 px) and use it. Text sizes: title 22 px, section titles 16 px, meta text 14 px. The stepper is a vertical list on a narrow screen (below 640 px). Check the widths 360, 768, and 1280 px with screenshots. Order on the job page: header, stepper, status block, **summary** (its own card, behind the status block), hints, "Technische Details", action bar.
- **Section 7 (top bar).** Remove "vdev" and every "dev" text from the top bar. Show the version only in a small footer and on the settings page, from the package metadata. Remove the second link "Bücherei". The top bar has the logo link "Haldio" on the left and "Einstellungen" on the right.
- **Section 8 (settings).** Build the real page as in Correction 5, section 8. Work in this order, one commit each:
  a. Override file `data/settings.local.yaml`, merge over `config.yaml` when a job starts, validation, "Auf Standard zurücksetzen". `config.yaml` stays unchanged.
  b. Card "Sprachmodell (LLM)": address, model dropdown with "Modelle laden", "Verbindung testen".
  c. Card "Sprecher (TTS)": speaker list with readable names, description, main language, "Hörprobe" (existing sample files first; "Hörprobe erzeugen" only through the model guard), "Qualität", "TTS testen".
  d. Cards "Ausgabe", "Ablauf", "Erweitert". Host and port are read-only with "Neustart nötig".
  e. **No file paths in the UI.** Remove the row "Daten" and every other path. Add `docs/configuration.md` and a link "Dokumentation".
- **Section 1 (open item).** Token count for long LLM requests: use `stream=true`, show "das Sprachmodell schreibt seit 38 s (etwa 410 Token)". If the model server does not support streaming, keep the elapsed time and say so in `PROGRESS.md`.
- **Section 9 (tests and screenshots).** Add the missing tests (top bar: one logo link, no "dev" text; settings: save with validation, override file, reset, no path in the rendered HTML, model list with a fake LM Studio, guard on "Hörprobe erzeugen" and "TTS testen"). Make the full screenshot set: running editing job with the live detail, "wartet auf das Entladen des LLM", speaking, failed job, finished job, review page with an empty section, library with 3 jobs, and the settings page. Light and dark. Put them in `docs/screenshots/`.

## 2. Extra findings from `PROGRESS.md` (check each one, fix if it is true)

1. **`page_count` is parsed from a progress note** ("N Seiten gelesen"). Do not parse text that is made for people. Write `page_count` as a field from the ingest stage. Add a test.
2. **Where does the 5-second gate re-check run?** The text "after 300 polls" suggests that the browser polls drive it. It must run in the worker (or a server timer) and must not depend on an open browser tab (a tab in the background runs timers slowly, and a closed tab does not run them). Test: the job continues when no HTTP request arrives. Count the 5 minutes in seconds, not in polls.
3. **Summary.** `quick_summary()` joins "heading: first paragraph". Keep it as the fallback only. The planning stage must make the real summary (5 to 8 sentences) and the main topics, as the brief says in S3 (the LLM runs in that stage anyway). If the LLM call fails, use the fallback. Store which source was used.
4. **Truncated originals.** Your explanation (small font and a fixed 260 px box) does not match my screenshots: the boxes were low and showed only two lines, for example "Der Change befindet sich". Check the facts for three chunks: the blocks in `*.in.json`, the text that the review page shows, and the PDF page. Does the original column show ALL blocks of a chunk (tables, lists, code, footnotes), or only paragraph text? If blocks are hidden, fix it and add a test. Write the result in `PROGRESS.md`.
5. Check if `data/voices.json` and the sample files per voice exist for the speaker cards. If not, say what I must run once (I run it; you do not).

## 3. Finish

- Update `PROGRESS.md` (states `done`, `partial`, `open` with proofs), the README, and `docs/configuration.md`.
- **Stop. Show me:** the screenshots, and one table "spec bullet → state → proof" for Correction 5. Wait for my OK.
