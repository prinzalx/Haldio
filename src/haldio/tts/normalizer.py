"""Text normalizer for TTS: pronunciations, numbers, identifiers (stage S8 helper)."""

from __future__ import annotations

import re
from pathlib import Path

_CAMEL = re.compile(r"(?<=[a-z0-9])(?=[A-Z])")
_DECIMAL_DE = re.compile(r"(?<=\d),(?=\d)")
_DECIMAL_EN = re.compile(r"(?<=\d)\.(?=\d)")
_STANDALONE_INT = re.compile(r"(?<![\w.])\d{1,4}(?![\w.])")


def load_pronunciations(path: Path) -> dict[str, str]:
    """Read pronunciations.yaml: term -> spoken form. Missing file means empty."""
    if not path.is_file():
        return {}
    import yaml

    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return {str(k): str(v) for k, v in raw.items()}


def _number_words(value: str, language: str) -> str:
    try:
        from num2words import num2words

        lang = "de" if language.startswith("de") else "en"
        return str(num2words(int(value), lang=lang))
    except Exception:
        return value


def speak_identifiers(text: str) -> str:
    """Split CamelCase and glue-free digit tails so TTS reads identifiers well."""
    result = _CAMEL.sub(" ", text)
    return result


def make_speakable(
    text: str, language: str = "de", pronunciations: dict[str, str] | None = None
) -> str:
    """Prepare one TTS unit: pronunciations first, then numbers, then identifiers."""
    result = text
    for term, spoken in (pronunciations or {}).items():
        result = result.replace(term, spoken)
    if language.startswith("de"):
        result = _DECIMAL_DE.sub(" Komma ", result)
    else:
        result = _DECIMAL_EN.sub(" point ", result)
    result = _STANDALONE_INT.sub(lambda m: _number_words(m.group(), language), result)
    return speak_identifiers(result)
