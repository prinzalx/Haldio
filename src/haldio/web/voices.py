"""The nine named speakers of the Qwen3-TTS CustomVoice model, German UI text.

Ids and dialects come from the qwentts.cpp README; the character notes are
the Qwen3-TTS README descriptions in simple German. The German note reminds
that the dialects only color Chinese speech, never German.
"""

from __future__ import annotations

from dataclasses import dataclass

GERMAN_NOTE = "Deutsch klingt unverändert"


@dataclass(frozen=True)
class SpeakerInfo:
    id: str
    label: str
    description: str
    language: str


SPEAKERS: tuple[SpeakerInfo, ...,] = (
    SpeakerInfo("serena", "Serena", "sanfte junge Frau", "Chinesisch"),
    SpeakerInfo("vivian", "Vivian", "klare, helle junge Stimme", "Chinesisch"),
    SpeakerInfo("uncle_fu", "Onkel Fu", "tiefe, ruhige Stimme", "Chinesisch"),
    SpeakerInfo("ryan", "Ryan", "engagiert und voll vorgetragen", "Englisch"),
    SpeakerInfo("aiden", "Aiden", "klare, süße Stimme", "Englisch"),
    SpeakerInfo("ono_anna", "Ono Anna", "energisches Mädchen", "Japanisch"),
    SpeakerInfo("sohee", "Sohee", "herzenswarme jüngere Schwester", "Koreanisch"),
    SpeakerInfo("eric", "Eric", "stadtischer Onkel aus Sichuan", "Sichuan"),
    SpeakerInfo("dylan", "Dylan", "schlauer Junge aus Peking", "Peking"),
)


def speaker_rows(selected: str) -> list[dict[str, object]]:
    """One row per speaker for the settings card; the chosen one is flagged."""
    return [
        {
            "id": s.id,
            "label": s.label,
            "text": f"{s.label} – {s.description} (Hauptsprache {s.language}; {GERMAN_NOTE})",
            "selected": s.id == selected,
        }
        for s in SPEAKERS
    ]
