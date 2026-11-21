# Configuration

The web UI shows readable names only. File paths live here.

## Files

| File | What it holds |
| --- | --- |
| `config.yaml` | The main settings, with comments. The UI never rewrites it. |
| `data/settings.local.yaml` | Your changes from the settings page. Merged over `config.yaml` when a job starts. "Auf Standard zurücksetzen" deletes it. |
| `.env` | Secrets, for example the API key. |
| `data/<job>/` | One folder per job: ingest text, script, audio units, master. |
| `data/samples/<voice>.wav` | Listening samples for the speaker card. |

Changes on the settings page apply to jobs that start **after** the save.
A running job keeps its settings.

## Sprachmodell (LLM)

| Setting | Default | Meaning |
| --- | --- | --- |
| `llm.base_url` | `http://127.0.0.1:8080/v1` | Where LM Studio runs. |
| `llm.model` | `bubo` | The model used for editing. |
| `llm.api_key` | `lm-studio` | Never shown in the UI, only "gesetzt"/"nicht gesetzt". Set your real key here or in `.env`. |
| `llm.temperature` | `0.2` | 0 = careful, 2 = creative. |
| `llm.timeout_s` | `600` | How long one model request may take, in seconds. |

Also in `config.yaml` only: `llm.max_input_tokens` (1500),
`llm.max_output_tokens` (4000), `llm.strip_thinking` (true).

## Sprecher (TTS)

| Setting | Default | Meaning |
| --- | --- | --- |
| `tts.speaker` | `dylan` in the upload form | The voice. Nine speakers are listed on the settings page. |
| `tts.language` | `auto` | Automatisch, Deutsch or Englisch. |
| `tts.qwencpp_port` | `8111` | Port of the local `tts-server`. |
| `tts.qwencpp_startup_timeout` | `300` | How long the TTS server start may take, in seconds. |
| `tts.max_chars_per_unit` | `400` | Unit size: how many characters one speech unit holds. |

Model files (set in `config.yaml` only, the UI shows the quality name):

- `tts.qwencpp_server` — `../_tools/qwentts.cpp/build/Release/tts-server.exe`
- `tts.qwencpp_model` — `../_tools/qwentts.cpp/models/qwen-talker-1.7b-customvoice-Q8_0.gguf`
  ("Standard (Q8)". A `Q4` file is offered as "Kleiner und schneller (Q4)"
  when it exists in the same folder.)
- `tts.qwencpp_codec` — `../_tools/qwentts.cpp/models/qwen-tokenizer-12hz-Q8_0.gguf`

## Ausgabe (audio)

| Setting | Default | Meaning |
| --- | --- | --- |
| `audio.formats` | `mp3`, `ogg` | Which files the master stage writes. |
| `audio.mp3_bitrate_kbps` | `96` | MP3 quality, 32 to 320. |
| `audio.pause_ms.paragraph` | `500` | Pause after a paragraph (shown as seconds). |
| `audio.pause_ms.heading` | `900` | Pause after a heading (shown as seconds). |
| `audio.pause_ms.chapter` | `1500` | Pause after a chapter (shown as seconds). |

Also in `config.yaml` only: `audio.channels` (1), `audio.target_lufs` (-18).

## Ablauf

| Setting | Default | Meaning |
| --- | --- | --- |
| `editor.review_before_tts` | `false` | Stop after the script so you can check it. |
| `tts.confirm_before_start` | `true` | Wait for you before reading aloud. |
| `editor.fallback_to_source` | `true` | Read the original text when a section has no Hörtext. |
| `editor.max_retries` | `2` | Retries of the control step, 0 to 5. |

## Server

`server.host` (127.0.0.1) and `server.port` (8505) are read-only in the UI:
change them in `config.yaml` and restart ("Neustart nötig").

## Other keys (config.yaml only)

Not on the settings page: `tts.backend` (mock), `tts.mode` (custom_voice),
`tts.model_id` (Qwen/Qwen3-TTS-12Hz-1.7B-Base), `tts.device` (auto),
`tts.dtype` (bfloat16), `editor.prompt_version` (v1), `editor.fidelity_check`
(true), `paths.data_dir` (data), `server.max_upload_mb` (100), and the
`hooks.before_edit` / `after_edit` / `before_speak` / `after_speak` commands
(empty by default).
