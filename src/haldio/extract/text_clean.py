"""Text helpers: line joining, hyphenation repair, cross-reference finding."""

from __future__ import annotations

import re

# Cross-reference labels in German and English (brief section 7).
_REF_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "section",
        re.compile(
            r"\b(?:abschnitt|kapitel|section|anh(?:hang)?|annex)\s+([0-9]+(?:[.,][0-9]+)*)",
            re.IGNORECASE,
        ),
    ),
    ("table", re.compile(r"\b(?:tabelle|table|tab\.)\s*([0-9]+[a-z]?)", re.IGNORECASE)),
    (
        "figure",
        re.compile(
            r"\b(?:abbildung|figur|figure|fig\.)\s*([0-9]+[a-z]?)",
            re.IGNORECASE,
        ),
    ),
    ("page", re.compile(r"\b(?:seite|page|pp?\.)\s*([0-9]+)", re.IGNORECASE)),
]

_BULLET_CHARS = "•●◦‣▪■○·–-"
_NUMBERED = re.compile(r"^\(?\s*([0-9]{1,2}|[a-z]|[ivxlcdm]{1,7})[.)]\s+", re.IGNORECASE)


def is_bullet_line(text: str) -> bool:
    """True when a line starts with a bullet character."""
    stripped = text.strip()
    return bool(stripped) and stripped[0] in _BULLET_CHARS


def list_marker(text: str) -> str | None:
    """Return the list marker of a line, or None when it is not a list item."""
    if is_bullet_line(text):
        return text.strip()[0]
    match = _NUMBERED.match(text)
    return match.group(0).strip() if match else None


def strip_list_marker(text: str) -> str:
    """Remove a leading bullet or numbering from a list item text."""
    stripped = text.strip()
    match = _NUMBERED.match(stripped)
    if match:
        return stripped[match.end() :].strip()
    if stripped and stripped[0] in _BULLET_CHARS:
        return stripped[1:].strip()
    return stripped


def repair_hyphenation(text: str) -> str:
    """Join a line break that split one word.

    Only lowercase-lowercase joins lose the hyphen. `PDF-\\nKonverter` keeps it.
    """

    def join(match: re.Match[str]) -> str:
        before, after = match.group(1), match.group(2)
        if before.islower() and after.islower():
            return before + after
        return f"{before}-{after}"

    return re.sub(r"([A-Za-zäöüßÄÖÜ])- ?\n ?([A-Za-zäöüßÄÖÜ])", join, text)


def join_lines(lines: list[str]) -> str:
    """Join text lines into one paragraph, fixing hyphenation first."""
    if not lines:
        return ""
    fixed = [line.strip() for line in lines if line.strip()]
    if not fixed:
        return ""
    text = fixed[0]
    for next_line in fixed[1:]:
        if text.endswith("-") and text[-2:-1].islower() and next_line[:1].islower():
            text = text[:-1] + next_line
        elif text.endswith("-"):
            text = text + next_line
        else:
            text = f"{text} {next_line}"
    return re.sub(r"\s+", " ", text).strip()


def find_cross_references(text: str) -> list[tuple[str, str]]:
    """Return (kind, label) pairs for references like 'section 4.2' or 'Tabelle 3'."""
    found: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for kind, pattern in _REF_PATTERNS:
        for match in pattern.finditer(text):
            pair = (kind, match.group(1))
            if pair not in seen:
                seen.add(pair)
                found.append(pair)
    return found
