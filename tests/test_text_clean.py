"""Tests for the text helpers used by extraction."""

from __future__ import annotations

from haldio.extract.text_clean import (
    find_cross_references,
    join_lines,
    list_marker,
    repair_hyphenation,
    strip_list_marker,
)


def test_join_lines_fixes_hyphenation() -> None:
    text = join_lines(["die Grundidee der Verwen-", "dung von Grundstoffen."])
    assert text == "die Grundidee der Verwendung von Grundstoffen."


def test_join_lines_keeps_word_hyphens() -> None:
    text = join_lines(["der PDF-", "Konverter arbeitet leise."])
    assert text == "der PDF-Konverter arbeitet leise."


def test_repair_hyphenation_on_raw_text() -> None:
    assert repair_hyphenation("Verwen-\ndung") == "Verwendung"
    assert repair_hyphenation("PDF-\nKonverter") == "PDF-Konverter"


def test_list_marker_detects_bullets_and_numbers() -> None:
    assert list_marker("\u2022 die Spannung")
    assert list_marker("2. der Punkt") == "2."
    assert list_marker("normaler text") is None


def test_strip_list_marker() -> None:
    assert strip_list_marker("\u2022 die Spannung") == "die Spannung"
    assert strip_list_marker("a) der Punkt") == "der Punkt"


def test_find_cross_references_german_and_english() -> None:
    text = "Siehe Abschnitt 4.2, Tabelle 3 und page 12. Abbildung 2 zeigt mehr."
    found = find_cross_references(text)
    assert ("section", "4.2") in found
    assert ("table", "3") in found
    assert ("page", "12") in found
    assert ("figure", "2") in found
