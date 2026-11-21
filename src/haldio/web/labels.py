"""German status labels and the stage stepper for the web UI.

One function per question so templates never show a raw status id.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from haldio.jobs.index import Job

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

_STATE_ICONS = {
    "done": "✓",
    "current": "▶",
    "failed": "✗",
    "pending": "•",
    "waiting": "⏸",
}
# waiting statuses: the stage that waits (rows before it are done)
_WAITING_STAGE = {
    "awaiting_review": 4,
    "awaiting_tts": 5,
    "waiting_for_user": 5,
}
_STATE_WORDS = {
    "done": "fertig",
    "current": "läuft",
    "failed": "fehlgeschlagen",
    "pending": "offen",
    "waiting": "wartet",
}
_STAGE_NAMES = [name for name, _label in STAGES]


def status_label(status: str) -> dict[str, str]:
    """Label data for a status id; unknown ids fall back to the raw id."""
    found = STATUS_LABELS.get(status)
    if found is not None:
        return found
    return {"label": status, "icon": "•", "cls": ""}


def stepper_state(job: Job) -> list[dict[str, Any]]:
    """The seven stepper rows, derived from ONE source (the job record).

    Every status maps to exactly one row set, so the stepper can never
    disagree with the status badge: running stages mark the current stage,
    waiting statuses mark the stage that waits as "waiting" (never "läuft"),
    a failed or cancelled job stops at the stage the worker last reported.
    """
    status = str(getattr(job, "status", ""))
    activity = getattr(job, "activity", None) or {}
    stage = str(activity.get("stage") or job.options.get("stage", ""))
    current = _STAGE_NAMES.index(stage) if stage in _STAGE_NAMES else None
    rows: list[dict[str, Any]] = []
    for index, (name, label) in enumerate(STAGES):
        if status == "done":
            state = "done"
        elif status in ("failed", "cancelled"):
            stop = current if current is not None else 0
            state = ("done" if index < stop else "failed" if index == stop else "pending")
        elif status == "queued":
            state = "waiting" if index == 0 else "pending"
        elif status in _WAITING_STAGE:
            stop = _WAITING_STAGE[status]
            state = "done" if index < stop else "waiting" if index == stop else "pending"
        else:
            active = current if current is not None else _STATUS_STAGE.get(status, 0)
            state = "done" if index < active else "current" if index == active else "pending"
        rows.append(
            {
                "name": name,
                "label": label,
                "state": state,
                "icon": _STATE_ICONS[state],
                "word": _STATE_WORDS[state],
            }
        )
    return rows


# editor warning codes -> readable German reason (never show the raw code)
REASON_GERMAN = {
    "table_large": "Große Tabelle",
    "formula_complex": "Komplizierte Formel",
    "code_omitted": "Code weggelassen",
    "ambiguous_reference": "Bezug nicht eindeutig",
    "unclear_source": "Quelle schwer lesbar",
    "needs_review": "Abschnitt zur Prüfung",
    "no_script": "Kein Hörtext",
    "other": "Hinweis",
}


def warning_text(warning: object) -> str:
    """A readable German line for one editor warning (dict or plain string)."""
    if isinstance(warning, dict):
        kind = REASON_GERMAN.get(str(warning.get("type", "other")), "Hinweis")
        detail = str(warning.get("detail", "")).strip()
        return f"{kind}: {detail}" if detail else kind
    return REASON_GERMAN.get(str(warning).strip(), str(warning))
