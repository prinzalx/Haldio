"""The nine named speakers of the Qwen3-TTS CustomVoice model.

Ids come from the qwentts.cpp README. Only the plain names are shown in the
UI - the owner asked for no description text.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SpeakerInfo:
    id: str
    label: str


SPEAKERS: tuple[
    SpeakerInfo,
    ...,
] = (
    SpeakerInfo("serena", "Serena"),
    SpeakerInfo("vivian", "Vivian"),
    SpeakerInfo("uncle_fu", "Onkel Fu"),
    SpeakerInfo("ryan", "Ryan"),
    SpeakerInfo("aiden", "Aiden"),
    SpeakerInfo("ono_anna", "Ono Anna"),
    SpeakerInfo("sohee", "Sohee"),
    SpeakerInfo("eric", "Eric"),
    SpeakerInfo("dylan", "Dylan"),
)


def speaker_rows(selected: str) -> list[dict[str, object]]:
    """One row per speaker for the settings card; the chosen one is flagged."""
    return [
        {
            "id": s.id,
            "label": s.label,
            "text": s.label,
            "selected": s.id == selected,
        }
        for s in SPEAKERS
    ]
