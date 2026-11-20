# Reference notes — ebook2audiobook

Studied read-only at `../_reference/ebook2audiobook` (shallow clone) on 2026-11-20.
Purpose: what to borrow as a *concept*. We do not copy code.

## Structure and license

- Not one giant file, but top-heavy: `lib/core.py` **5484 lines** (pipeline, ffmpeg,
  resume DB, normalisation), `lib/gradio.py` 4949 (GUI), `lib/conf_lang.py` 2620
  (language and punctuation tables), `lib/conf_models.py` 1157 (engine registry),
  `app.py` 791 (CLI entry). The modular part is `lib/classes/tts_engines/` (24 engines).
- License: **Apache-2.0**. Copying code needs attribution and NOTICE retention, and the
  copied part stays Apache-2.0. Our AGPL project may consume it.
- PDF input: no layout-analysis library. `pymupdf` page loop with `page.get_text("xhtml")`
  (`ocr2xhtml`, core.py:1157-1188); image-only pages are OCR'd at 300 dpi. Every other
  format goes through Calibre `ebook-convert` to EPUB, then `ebooklib`.
- **No LLM editorial stage.** Cleanup is rule-based (regex, num2words, stanza NLP at
  core.py:1668). Translation is Argos through a Calibre plugin. There is interactive
  sentence editing by a human, not by a model.

## 1. Sentence splitting

- Homegrown `get_sentences()` (core.py:2074). Text is packed into **segments bounded by a
  per-language character budget**, not grammatical sentences.
- Budget per ISO-639-3 code in `lib/conf_lang.py:956` (`max_chars`, e.g. 250 for English,
  71 for Japanese); the working limit is `max_chars / 2` (core.py:2269).
- Overlong segment → `_force_split_segment()` (core.py:2218) regresses from the window edge
  to the last hard punctuation, then soft punctuation, then whitespace, then hard-cuts.
  The punctuation sets are defined per writing system (`conf_lang.py:160-197`).
- Under-full "orphan" segments are merged into a neighbour up to a merge ceiling
  (core.py:2378-2400).
- Abbreviations are **expanded to words before** splitting (`normalize_text()`,
  core.py:3034-3075), longest-key-first, plus an acronym regex for `a.b.c` patterns.
  They are not handled by the splitter.

## 2. Language handling

- Language keyed by **ISO 639-3** with a derived 2-letter code for num2words/stanza.
- Validation happens in the engine: each engine checks its own supported-language map and
  raises (e.g. `piper.py.__init__`).
- Voice table: `lib/conf_models.py` maps engine → `{iso3: engine_code}`, plus sample rate
  and VRAM/CPU ratings, optional preset voice ids (`"eng": "af_heart"` for Kokoro).
- Text normalisation before TTS is a large rule pipeline: `set_formatted_number()` (2503),
  `get_num2words_compat()` (2475), `year2words`, `currency2words`, `math2words`,
  `clock2words`; punctuation that causes hallucinations is swapped per language
  (`punctuation_switch`).

## 3. TTS engine calls

- Registry by subclassing: `tts_registry.py` uses `__init_subclass__(cls, *, name)` and a
  dict `TTSRegistry.ENGINES`; duplicate names are rejected. Adding an engine = one class
  with `convert(sentence_number, sentence)`.
- Dispatcher `tts_manager.py` resolves the class from the session and calls
  `convert_sentence2audio(...)`. Some engines run in separate subprocess workers.
- No per-engine healthcheck method; only `check_programs()` (core.py:489) for external
  binaries. Voice listing is preset/session driven.
- Internal processing format is fixed: `flac` at 24000 Hz (`lib/conf.py:390-391`); each
  engine resamples from its own model rate.

## 4. Joining audio and chapters with ffmpeg

- Sentences → block: writes `concat_list_sentences.txt`, then the **concat demuxer** with
  re-encode (`-f concat -i list.txt -c:a <codec> -map_metadata -1`), see
  `assemble_audio_chunks()` (core.py:4387).
- Chapters add `-filter_complex` with `sidechaincompress` ducking for interlude music and
  `amix=...:normalize=0`; silence gaps come from `anullsrc` + `atrim` (core.py:4208).
- Chapter markers: a generated `FFMETADATA1` file with `[CHAPTER] TIMEBASE=1/1000 START END`
  (`_generate_ffmpeg_metadata()`, core.py:3726); chapter end found with
  `silencedetect=noise=-50dB:d=0.3`.
- Final export probes the input codec/rate; if it matches, `-c copy`, else re-encode per
  format (mp3 libmp3lame 192k @44100, m4b aac +faststart, opus @48k). Loudness step is
  `dynaudnorm` — **not** EBU `loudnorm`.
- Long books are split into parts by hours; the temp mix dir is removed after each part.

## 5. Recovery and error handling

- A SQLite "stamp" DB (core.py:760-1000) stores one resume pointer row (page, block,
  sentence, voice, engine) plus a per-block sentence table. It is saved every 5 seconds and
  after each chapter.
- Sentence-level cache: one file per sentence in a block dir. On resume, existing files are
  skipped, missing ones are re-synthesised and reported (core.py:3612).
- One failed sentence aborts the loop with a warning, but the stamp keeps progress, so the
  next run resumes (core.py:3620). After an edit, stale block dirs are deleted.
- Old temp dirs are cleaned by age: `tmp_expire = 60` days (`delete_unused_tmp_dirs()`).

## What we take, what we leave

| Take | Leave |
|---|---|
| Hard→soft→space→hard-cut fallback for over-long TTS units | Per-language char budgets tuned for one model family |
| Expanding abbreviations before splitting | Character-budget segmentation (our chunking is structural) |
| Registry-by-subclass pattern for TTS engines | 24 engines and their VRAM tables |
| Concat demuxer with a list file; FFMETADATA1 chapters | `dynaudnorm` (we need EBU `loudnorm` for a target LUFS) |
| Cache-per-unit plus a resume pointer | SQLite and per-sentence files (we use content hashes) |
| — | PDF layout analysis (none) and an editorial stage (none) |

**Fork verdict:** the study confirms the brief. Their value is format breadth and engine
breadth; our value (PDF layout + editorial LLM stage) is absent there. No reason to fork.
