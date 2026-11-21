"""User settings in data/settings.local.yaml, merged over config.yaml.

config.yaml keeps its comments and is never rewritten. The override file
holds only what the user changed on the settings page; a job reads the
merged result when it starts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from haldio.config import Config

OVERRIDE_NAME = "settings.local.yaml"


def override_path(data_dir: Path) -> Path:
    return data_dir / OVERRIDE_NAME


def load_override(data_dir: Path) -> dict[str, Any]:
    """The saved overrides, {} when there is no file. Nested dict by section."""
    path = override_path(data_dir)
    if not path.is_file():
        return {}
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return raw if isinstance(raw, dict) else {}


def save_override(data_dir: Path, values: dict[str, Any]) -> None:
    path = override_path(data_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(values, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def clear_override(data_dir: Path) -> None:
    override_path(data_dir).unlink(missing_ok=True)


def apply_override(base: Config, values: dict[str, Any]) -> Config:
    """A copy of base with the nested override values applied.

    Unknown sections or keys are ignored, so an old override file never
    breaks a newer build.
    """
    effective = base.model_copy(deep=True)
    for section, updates in values.items():
        part = getattr(effective, section, None)
        if part is None or not isinstance(updates, dict):
            continue
        for key, value in updates.items():
            if hasattr(part, key):
                setattr(part, key, value)
    return effective


def effective_config(base: Config) -> Config:
    """Base config with the data-dir override file merged over it."""
    return apply_override(base, load_override(base.paths.data_dir))


def parse_form(data: dict[str, str]) -> tuple[dict[str, object], dict[str, str]]:
    """Turn the settings form into nested values, validating every field.

    Returns (values by section, errors by field name). German error texts;
    a field with an error keeps its old value (it is not saved).
    """
    values: dict[str, object] = {}
    errors: dict[str, str] = {}

    def put(section: str, attr: str, value: object) -> None:
        values.setdefault(section, {})[attr] = value  # type: ignore[index]

    url = (data.get("llm.base_url") or "").strip()
    if url.startswith(("http://", "https://")):
        put("llm", "base_url", url)
    else:
        errors["llm.base_url"] = "Adresse muss mit http:// oder https:// beginnen."

    model = (data.get("llm.model") or "").strip()
    if model:
        put("llm", "model", model)
    else:
        errors["llm.model"] = "Modellname darf nicht leer sein."

    speaker = (data.get("tts.speaker") or "").strip()
    if speaker:  # an empty field keeps the default, it never wipes it
        put("tts", "speaker", speaker)
    language = data.get("tts.language") or "auto"
    if language in ("auto", "de", "en"):
        put("tts", "language", language)
    else:
        errors["tts.language"] = "Sprache ist unbekannt."

    formats = [name for name in ("mp3", "ogg") if data.get(f"audio.format.{name}") == "on"]
    if formats:
        put("audio", "formats", formats)
    else:
        errors["audio.format.mp3"] = "Wählen Sie mindestens ein Format."

    bitrate = (data.get("audio.mp3_bitrate_kbps") or "").strip()
    if bitrate.isdigit() and 32 <= int(bitrate) <= 320:
        put("audio", "mp3_bitrate_kbps", int(bitrate))
    else:
        errors["audio.mp3_bitrate_kbps"] = "Bitrate: ganze Zahl von 32 bis 320."

    for name, section, attr in (
        ("editor.review_before_tts", "editor", "review_before_tts"),
        ("tts.confirm_before_start", "tts", "confirm_before_start"),
        ("editor.fallback_to_source", "editor", "fallback_to_source"),
    ):
        put(section, attr, data.get(name) == "on")

    retries = (data.get("editor.max_retries") or "").strip()
    if retries.isdigit() and 0 <= int(retries) <= 5:
        put("editor", "max_retries", int(retries))
    else:
        errors["editor.max_retries"] = "Wiederholungen: ganze Zahl von 0 bis 5."

    return values, errors
