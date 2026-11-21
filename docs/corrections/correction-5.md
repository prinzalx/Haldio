# Correction 5: status, feedback, review page, job page, settings

I tested the web interface with a real PDF (36 pages) and made screenshots. These points are wrong or missing. Check each point against the current code. Write the result in `docs/PROGRESS.md` (fixed, not needed, or open).

## 0. Rules

- **A test run can still be active.** Do not touch `data/`. Do not stop or restart `haldio serve` (port 8505). Do not start a model, `tts-server`, or `check_qwencpp.py`. I restart the server myself.
- For screenshots and tests, use `scripts/screenshots.py` with a temporary data directory, mock data, and a different port.
- Keep all existing tests green. Add tests for each fix. Run `ruff`.
- Work in the order of the sections. Commit after each section.

## 1. One source for the status (most important)

What I saw in the test:
- I clicked "OK — Sprachausgabe starten". The page did not change. It still said "Bereit für Sprachausgabe", and the stepper still said "Redigieren (läuft)". I saw no sign that anything happens. (In the old code, polling stops in the state `awaiting_tts`. Check this.)
- Then the job went to a second pause: "LLM stoppen, dann Weiter drücken." I had stopped the LLM already. I did not see this pause, because the page did not update. I had to click "Weiter" a second time. Only then the PC worked.
- When I came back from the review page, the page looked different (title, page count, stepper). So the first page was old, not wrong data.
- The stepper and the badge disagree: "Sprechen (läuft)" next to "Wartet auf Sie".
- The log shows only `editing 58%` (stage id and percent, sometimes the same line five times). It did not update during speech synthesis. It is duplicate and inconsistent information.
- The speech stage shows a good status: "Einheit 17 von 944 · noch ca. 14 min". The editing stage has nothing like it.

Do this:
1. **One activity record for each job.** The worker writes it through ONE function `emit(...)`. Fields: `state` (running, waiting, failed, done), `stage`, `done`, `total`, a short German `detail` sentence, `eta`, `updated_at`. The stepper, the status block, and the log all read from this record. No second source, no second text.
2. **Every stage shows its own detail in the status block, like the speech stage does now.** Examples: Hörtext schreiben: "Abschnitt 14 von 40 · noch etwa 25 min". Kontrollieren: "Abschnitt 14 von 40". Vorlesen: as now. Audio fertigstellen: "Teil 2 von 3: MP3".
3. **Time estimate.** Show it only after 5 finished items. Use the average of the last 10 items. Do not count cache hits and failed (silent) units. Write "etwa". In the test, "noch ca. 14 min" for 944 units after 17 units looks too low. Check the formula.
4. **Sign of life.** A moving indicator (spinner) shows ONLY when something runs. When the job waits, show a grey "Pause – es läuft nichts". Show "zuletzt aktiv vor N s". If a running job has no update for 60 seconds, show a warning "Keine Aktivität seit N s".
5. **Long LLM requests** (more than a minute): show in the status block "das Sprachmodell schreibt seit 38 s (etwa 410 Token)". Use `stream=true` and count the tokens. If this is hard, show only the elapsed time.
6. **The log is the second channel, for problems.** Rename it "Technische Details". Collapsed by default, with a counter "N Einträge". It reads the same `emit` events. Rules: one line for each real event, never the same line twice, no lines with only stage id and percent. Each line has a time stamp and a level (INFO, WARN, ERROR; a text marker and a color). Show the last 200 lines in a box with its own scroll bar. Add the endpoint `GET /jobs/<id>/log?after=<n>` (only new lines; poll it only while the box is open). Write the same lines to `logs/job.log`. Add a link "Protokoll herunterladen". The log must update in EVERY stage (also speech and mastering). For the console of `haldio serve`, one standard `logging` handler with the same text is enough. No extra work.
7. **What a log line says:** WHAT happened, to WHICH part, with WHAT result. Use only data that the program already has. Examples:
   - `Hörtext: Abschnitt 14/40 fertig nach 41 s (1480 Zeichen), 1 Warnung: große Tabelle`
   - `Kontrolle: Abschnitt 14/40 – Fachbegriff "XYZ" fehlt, neuer Versuch 1 von 2`
   - `Hörtext: Abschnitt 15/40 aus dem Zwischenspeicher übernommen`
   - `Hörtext: fertig – 40 Abschnitte, 7 Warnungen, 3 neue Versuche, 2 zur Prüfung markiert, Dauer 52 min`
   - `Vorlesen: Einheit 12/944 fertig (4,1 s Audio in 3,2 s)`
   - Errors: a short German text, then a detail line with the cause. Lines of `tts-server` and `ffmpeg` are marked with their source.

## 2. Buttons, polling, and the two gates

1. **Polling in every state that is not final:** queued, all work stages, `awaiting_review`, `awaiting_tts`, `waiting_for_user`. Stop only in `done`, `failed`, `cancelled` (after one last refresh). Refresh also when the tab becomes visible again (`visibilitychange`) and when the page returns with the Back button (`pageshow`, no old cached page).
2. **Feedback after each click.** The button becomes disabled with a spinner and a text ("Wird gestartet …"). The response replaces the status block at once (HTMX, no full reload) and shows the new state ("In Warteschlange", "Prüfe LM Studio …"). Show a toast. The page never stays unchanged after a click.
3. **Stepper from one pure function** `stepper_state(job)`, tested with a table for every status. It always agrees with the badge. Examples: `awaiting_tts` → Einlesen to Skript fertig, Sprechen "wartet", Mastern offen. `waiting_for_user` in the speech stage → Sprechen "wartet auf Sie". `failed` → the stage that failed shows "fehlgeschlagen".
4. **One gate, not two.** Now: first "OK — Sprachausgabe starten", then a second pause from the model guard, although the LLM was stopped. Change it: the OK button starts one flow. The guard checks LM Studio. If a model is still loaded, show its name (no path) and "Ich prüfe alle 5 Sekunden weiter". Continue by itself as soon as the model is gone (LM Studio can need some seconds to unload). After 5 minutes without change, show a button "Erneut prüfen". Ask for a manual "Weiter" only if the check is not possible. Explain in plain words how to unload (in LM Studio: eject the model, or stop the server).
5. **Colors.** "Bitte alle anderen lokalen LLM beenden." is red like an error. Use a neutral or yellow information box with an icon and numbered steps. Use red only for errors.
6. Before the speech starts, show a short check list that updates: "Sprachmodell entladen ✓ · TTS-Server startet … · Stimme dylan".

## 3. Review page ("Skript prüfen")

What I saw: no explanation why the page exists. Raw codes like `needs_review`. For several sections, the script column is empty and has no input field, so I cannot correct anything. I do not know what is wrong in a section.

1. **Intro text** at the top (German, short): "Hier sehen Sie den Hörtext, den das Sprachmodell geschrieben hat. Links steht das Original, rechts der Hörtext. Gelb markierte Abschnitte hat die automatische Kontrolle beanstandet. Sie können den Hörtext rechts ändern und speichern. Sie müssen nichts tun: Ohne Änderung wird der Text so vorgelesen." Add: "Geänderte Texte werden nicht erneut geprüft."
2. **Each section:** a readable heading (chapter path and "Seite 17", not the first words of the text, no leftover bullet characters). A reason in German instead of the raw code, and the findings of the control step as a list (for example: Fachbegriff fehlt, Zahl geändert, keine Antwort vom Sprachmodell). Save the findings in the chunk record if they are not stored yet.
3. **Every section has an input field,** also when the script is empty. For an empty script, show the warning "Für diesen Abschnitt gibt es keinen Hörtext." with two buttons: "Original übernehmen" (copies the original text into the field) and "Neu erzeugen" (starts the LLM for this section; allowed only when LM Studio is reachable, otherwise show a hint).
4. **No silent loss of content.** An empty section must never be skipped without notice. Add the setting `editor.fallback_to_source` (default true): the speech stage reads the original text of such a section (after the normal normalizer). Write a log line and a mark in the QA report. Show the count on the job page and before the speech starts: "5 Abschnitte ohne Hörtext – es wird der Originaltext vorgelesen."
5. **Original text complete?** Some originals end in the middle of a sentence ("Der Change befindet sich", "… und alle während des Changes auftretenden"). Find out the cause: only the display, the chunker, or the extractor (text lost). Compare with the PDF (use `haldio inspect`). If text is lost, fix the extractor and add a test.
6. Original and script use the same font and size. Long lines wrap. The button "Speichern" is enabled only after a change and shows "Gespeichert". Show a counter "12 von 40 Abschnitten mit Hinweis". The filter has a clear label. If there are no hints, show all sections.
7. The job page shows a clear entry "Skript prüfen (optional)" with the number of hints, when the state is `awaiting_review` or `awaiting_tts`.

## 4. Plain language for the steps

"Redigieren" is a word that many people do not know. Change the words in the whole UI. Keep the internal status ids.

| id | New label | One-sentence explanation (show in the UI) |
|---|---|---|
| `extracting` | Einlesen | Das PDF wird geöffnet. Text, Überschriften, Tabellen und Listen werden erkannt. |
| `planning` | Planen | Kapitel, Fachbegriffe und Verweise werden gesammelt. Daraus entsteht die Zusammenfassung. |
| `editing` | Hörtext schreiben | Das lokale Sprachmodell schreibt jeden Abschnitt so um, dass man ihn gut hören kann. Tabellen und Listen werden zu Sätzen, Zahlen und Einheiten werden ausgeschrieben, Verweise werden erklärt. Der Inhalt bleibt gleich. |
| `verifying` | Kontrollieren | Eine automatische Prüfung sucht Fehler: fehlende Fachbegriffe, geänderte Zahlen, erfundene Inhalte. Bei einem Fehler wird der Abschnitt neu geschrieben. |
| (script) | Skript erstellen | Alle Abschnitte werden zum fertigen Hörbuch-Skript zusammengefügt. |
| `speaking` | Vorlesen | Die Stimme (Qwen3-TTS, Sprecher dylan) liest das Skript vor. |
| `mastering` | Audio fertigstellen | Die Teile werden zusammengeschnitten, die Lautstärke wird angeglichen, MP3 und OGG werden erzeugt. |

- Show a box "Gerade:" under the stepper: the label, the explanation of the current step, and the live detail from section 1. Add a small `<details>` "Was bedeuten die Schritte?" with the whole table. Each stepper chip has a `title` with its explanation.
- The percent value is for the whole job. Show "Gesamt 32 %". The detail of the step is in the status block.

## 5. Layout errors on the job page

1. **Progress is shown twice.** Keep ONE progress block: the stepper (it shows the step) and ONE bar with the percent value. Remove the badge with the step name next to the bar. The message line shows only the detail. It never repeats the step name or the percent value.
2. **The buttons are squeezed in a corner.** Make one action bar at the bottom of the card: a separator line above it, `flex` with `gap` and `flex-wrap`. On the left: the main action for the state ("Abbrechen" while the job runs). Then "Zurück" as a normal link. "Löschen" is separated (far right). While the job runs, hide or disable "Löschen".
3. **Contrast.** "Löschen" has light red text on a dark red button. Use white text on the danger color (WCAG AA).
4. **Empty placeholders.** Remove "?" and "—" from the view:
   - Page count: save it in the job record in the stage "Einlesen". If it is unknown, hide the field.
   - "Zusammenfassung —" and "Themen —" are still empty, but "Planen" is done. Find out why. The brief says: make the summary from the headings and the first paragraphs of each chapter. Fix it. While the data is missing, show "Wird erstellt …".
   - Show the file name only once, if it equals the title. If the PDF has no title, take the first top-level heading, or the file name without `.pdf`.
5. **Library list.** The same file name appears twice and the meta line wraps in a bad way. Line 1: title (link). Line 2: small muted meta text (pages, date, audio length; only fields that exist). Right side: status badge, thin progress bar, "Öffnen", "Löschen" (separated). On a narrow screen, the right side moves below.

## 6. A calmer, more polished look

- One spacing scale (4, 8, 12, 16, 24, 32 px) as CSS variables. Clear text hierarchy: title 22 px bold, section titles 16 px, meta text 14 px muted. Thin lines between the sections of a card.
- Order on the job page: header, stepper, status block, summary, hints, "Technische Details", action bar.
- The stepper wraps nicely. On a narrow screen, it becomes a vertical list.
- Colors: running (blue), done (green), error (red), waiting (yellow), information (neutral). Always an icon and a text.
- Check light and dark theme, and the widths 360, 768, and 1280 px.

## 7. Top bar

1. **"vdev" in the top right corner.** The page shows the fallback text "dev" when no version is passed. Remove it from the top bar. Show the version only in a small footer or on the settings page. Read it from the package metadata (`importlib.metadata`). Never show a placeholder.
2. **Two links with the same target.** "Haldio" and "Bücherei" both lead to `/`. Keep only the logo link "Haldio". Remove "Bücherei". The top bar has the logo on the left and "Einstellungen" on the right. Mark the current page with `aria-current="page"`.

## 8. Settings page

The page is only a display now. It must be a real settings page. The text is German. It follows the rules of Correction 4 (guard, POST, CSRF, escaping).

**Rules for the page**
- Show NO file paths and no folder names. Not in the table, not in hints, not in error messages. Show readable names instead (for example "Qwen3-TTS 1.7B, CustomVoice, Qualität Q8"). Put the paths in the documentation: add `docs/configuration.md` (each setting, its default, its place in `config.yaml`, and the model file paths). In the UI, show only a link text "Dokumentation".
- Each setting has a label, a field, and a short hint in plain language. No raw config keys, no strings with many values in one line.
- Cards: "Sprachmodell (LLM)", "Sprecher (TTS)", "Ausgabe", "Ablauf", "Erweitert". Put rare settings (ports, timeouts, unit size, temperature) in "Erweitert" (collapsed).
- Save with a button "Speichern" and a toast. Validate the input and show a clear error text at the field.
- Save the changes in an override file in the data directory (for example `data/settings.local.yaml`). Merge it over `config.yaml` when a job starts. Do not rewrite `config.yaml` (it has comments). Add "Auf Standard zurücksetzen".
- A change applies to jobs that start AFTER the save. A running job keeps its settings. Say this in a hint. Do not restart anything.
- Settings that need a restart (host, port) are read-only with the text "Neustart nötig". Never show the API key ("gesetzt" or "nicht gesetzt").

**Card "Sprachmodell (LLM)"**
- Field "Adresse" (URL of LM Studio).
- Field "Modell" as a dropdown. Button "Modelle laden" calls the model list of LM Studio and fills the dropdown. Mark the models that are loaded now (if `lms` can tell). If the list cannot be loaded, show a clear error and a free text field.
- Button "Verbindung testen" with the result next to it: reachable or not, the model count, and whether the chosen model exists.

**Card "Sprecher (TTS)"**
- The speaker choice is confusing now. Replace it by a list of cards or a dropdown with the readable name, a short description, and the main language of each voice. Example: "Dylan – junge männliche Stimme (Hauptsprache Chinesisch; Deutsch klingt unverändert)". Take the names and descriptions from the nine speakers of the model (`data/voices.json` and the Qwen3-TTS README). Mark the chosen speaker. Add a field "Sprache" (Automatisch, Deutsch, Englisch).
- Button "Hörprobe" for each speaker. If a sample file exists (I made one sample for each voice earlier), play it with an `<audio>` element. If not, the button "Hörprobe erzeugen" starts the `tts-server` through the model guard, with the warning "Vorher das LLM entladen." Never start the `tts-server` without the guard.
- Field "Qualität" in plain words ("Standard (Q8)", "Kleiner und schneller (Q4)"), only for model files that exist. Names, not paths.
- Button "TTS testen" (POST, guard, warning text).

**Card "Ausgabe"**: check boxes for MP3 and OGG, the bit rate, and the pauses in seconds (Absatz, Überschrift, Kapitel).

**Card "Ablauf"**: "Skript vor der Sprachausgabe prüfen", "Vor dem Vorlesen auf mich warten" (`confirm_before_start`), "Bei fehlendem Hörtext den Originaltext vorlesen" (`editor.fallback_to_source`), and the number of retries of the control step.

## 9. Tests and finish

- Tests for: `emit` as the single source (status block, stepper, and log show the same event), `stepper_state` for every status, polling attributes in `awaiting_tts`, `awaiting_review`, and `waiting_for_user`, the gate flow with a fake guard (model loaded, then unloaded → continues by itself), the log endpoint (`after`), the estimate rule (no estimate before 5 items, no cache hits), the German label table, the page count and title logic, "Löschen hidden while the job runs".
- Review page: an empty section has an input field, `fallback_to_source` works (and writes the log line and QA mark), the reason texts are German, no raw code in the HTML.
- Settings and top bar: one logo link, no "dev" text, save with validation, override file, `config.yaml` unchanged, reset, no path in the rendered HTML and error texts (search for drive letters and path patterns), the model list with a fake LM Studio, the guard on "Hörprobe erzeugen" and "TTS testen".
- Update `scripts/screenshots.py`: running job (editing, with the live detail), waiting for the LLM to unload, speaking, failed job, finished job, review page with one empty section, library with 3 jobs, and the settings page. Light and dark. Put the PNG files in `docs/screenshots/`.
- Update the README (Web interface) and `docs/PROGRESS.md`.
- **Stop. Show me the screenshots. Wait for my OK.**
