"""German status labels and the stage stepper for the web UI.

One function per question so templates never show a raw status id.
"""

from __future__ import annotations

from typing import Any

# status id -> German label, icon, color class (badge-<status> in style.css)
STATUS_LABELS: dict[str, dict[str, str]] = {
    "queued": {"label": "Wartet", "icon": "⏳", "cls": "wait"},
    "extracting": {"label": "Einlesen", "icon": "📖", "cls": "run"},
    "planning": {"label": "Planen", "icon": "🗂", "cls": "run"},
    "editing": {"label": "Redigieren", "icon": "✍", "cls": "run"},
    "verifying": {"label": "Prüfen", "icon": "🔍", "cls": "run"},
    "script": {"label": "Skript", "icon": "📝", "cls": "run"},
    "awaiting_review": {"label": "Skript prüfen", "icon": "📝", "cls": "note"},
    "awaiting_tts": {"label": "Bereit für Sprachausgabe", "icon": "🔊", "cls": "note"},
    "waiting_for_user": {"label": "Wartet auf Sie", "icon": "🖐", "cls": "note"},
    "speaking": {"label": "Sprechen", "icon": "🔊", "cls": "run"},
    "mastering": {"label": "Mastern", "icon": "🎛", "cls": "run"},
    "done": {"label": "Fertig", "icon": "✅", "cls": "ok"},
    "failed": {"label": "Fehlgeschlagen", "icon": "❌", "cls": "bad"},
    "cancelled": {"label": "Abgebrochen", "icon": "⏹", "cls": "stop"},
}

# the seven pipeline stages shown in the job page stepper
STAGES: list[tuple[str, str]] = [
    ("extracting", "Einlesen"),
    ("planning", "Planen"),
    ("editing", "Redigieren"),
    ("verifying", "Prüfen"),
    ("script", "Skript"),
    ("speaking", "Sprechen"),
    ("mastering", "Mastern"),
]

# stage a job is at when it has this status and no stage hint was stored
_STATUS_STAGE: dict[str, int] = {
    "queued": 0,
    "extracting": 0,
    "planning": 1,
    "editing": 2,
    "verifying": 3,
    "script": 4,
    "awaiting_review": 4,
    "awaiting_tts": 5,
    "waiting_for_user": 5,
    "speaking": 5,
    "mastering": 6,
}

_STATE_ICONS = {"done": "✓", "current": "▶", "failed": "✗", "pending": "•"}
_STAGE_NAMES = [name for name, _label in STAGES]


def status_label(status: str) -> dict[str, str]:
    """Label data for a status id; unknown ids fall back to the raw id."""
    found = STATUS_LABELS.get(status)
    if found is not None:
        return found
    return {"label": status, "icon": "•", "cls": ""}


def stage_rows(status: str, hint: str = "") -> list[dict[str, Any]]:
    """One row per stage with state done/current/failed/pending.

    `hint` is the last stage the worker reported; it wins over the status map
    so a failed job shows where it stopped.
    """
    current = _STAGE_NAMES.index(hint) if hint in _STAGE_NAMES else _STATUS_STAGE.get(status, 0)
    rows: list[dict[str, Any]] = []
    for index, (name, label) in enumerate(STAGES):
        if status == "done" or index < current:
            state = "done"
        elif index == current:
            state = "failed" if status == "failed" else "current"
        else:
            state = "pending"
        rows.append(
            {
                "name": name,
                "label": label,
                "state": state,
                "icon": _STATE_ICONS[state],
            }
        )
    return rows


def warning_text(warning: object) -> str:
    """A readable German line for one editor warning (dict or plain string)."""
    if isinstance(warning, dict):
        kind = str(warning.get("type", "other"))
        detail = str(warning.get("detail", "")).strip()
        return f"{kind}: {detail}" if detail else kind
    return str(warning)
