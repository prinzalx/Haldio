"""User settings in data/settings.local.yaml, merged over config.yaml.

config.yaml keeps its comments and is never rewritten. The override file
holds only what the user changed on the settings page; a job reads the
merged result when it starts.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

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
    path.write_text(yaml.safe_dump(values, sort_keys=False, allow_unicode=True), encoding="utf-8")


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
            if not hasattr(part, key):
                continue
            current = getattr(part, key)
            if isinstance(current, BaseModel) and isinstance(value, dict):
                merged = {**current.model_dump(), **value}
                setattr(part, key, type(current)(**merged))
            else:
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
    model_file = (data.get("tts.qwencpp_model") or "").strip()
    if not model_file:
        pass  # keeps the configured model file
    elif Path(model_file).is_file():
        put("tts", "qwencpp_model", model_file)
    else:
        errors["tts.qwencpp_model"] = "Modell-Datei nicht gefunden."
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

    raw_pauses = {
        name: (data.get(f"audio.pause_ms.{name}") or "").strip()
        for name in ("paragraph", "heading", "chapter")
    }
    pauses: dict[str, int] = {}
    pause_error = False
    for name, raw in raw_pauses.items():
        if not raw:
            continue  # an empty field keeps that configured pause
        try:
            seconds = float(raw.replace(",", "."))
        except ValueError:
            seconds = -1.0
        if not 0 <= seconds <= 30:
            errors["audio.pause_ms"] = "Pause: Zahl zwischen 0 und 30 Sekunden."
            pause_error = True
            break
        pauses[name] = round(seconds * 1000)
    if not pause_error and pauses:
        put("audio", "pause_ms", pauses)

    temperature = (data.get("llm.temperature") or "").strip()
    if temperature:
        try:
            value = float(temperature.replace(",", "."))
        except ValueError:
            value = -1.0
        if 0 <= value <= 2:
            put("llm", "temperature", value)
        else:
            errors["llm.temperature"] = "Temperatur: Zahl zwischen 0 und 2."

    for name, section, attr, low, high, message in (
        ("llm.timeout_s", "llm", "timeout_s", 1, 3600, "Zeit: ganze Zahl von 1 bis 3600 Sekunden."),
        (
            "tts.max_chars_per_unit",
            "tts",
            "max_chars_per_unit",
            100,
            2000,
            "Einheitsgröße: ganze Zahl von 100 bis 2000.",
        ),
        ("tts.qwencpp_port", "tts", "qwencpp_port", 1, 65535, "Port: ganze Zahl von 1 bis 65535."),
        (
            "tts.qwencpp_startup_timeout",
            "tts",
            "qwencpp_startup_timeout",
            10,
            1800,
            "Startzeit: ganze Zahl von 10 bis 1800 Sekunden.",
        ),
    ):
        raw = (data.get(name) or "").strip()
        if not raw:
            continue  # empty field keeps the configured value
        if raw.isdigit() and low <= int(raw) <= high:
            put(section, attr, int(raw))
        else:
            errors[name] = message

    web_host = (data.get("server.host") or "").strip()
    if not web_host:
        pass  # empty field keeps the configured address
    elif any(c.isspace() for c in web_host):
        errors["server.host"] = "Web-Adresse: keine Leerzeichen erlaubt."
    else:
        put("server", "host", web_host)

    web_port = (data.get("server.port") or "").strip()
    if not web_port:
        pass  # empty field keeps the configured port
    elif web_port.isdigit() and 1 <= int(web_port) <= 65535:
        put("server", "port", int(web_port))
    else:
        errors["server.port"] = "Port: ganze Zahl von 1 bis 65535."

    return values, errors
