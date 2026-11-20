"""Tests for the PyMuPDF extractor against a synthetic PDF."""

from __future__ import annotations

import pytest

from haldio.extract import PyMuPDFExtractor
from haldio.inspect_report import format_inspect
from synthetic import HEADER, make_test_pdf


@pytest.fixture(scope="module")
def document(tmp_path_factory: pytest.TempPathFactory):
    path = make_test_pdf(tmp_path_factory.mktemp("pdf") / "doc.pdf")
    return PyMuPDFExtractor().extract(path)


def test_headings_get_levels(document) -> None:
    headings = {b.text: b.level for b in document.blocks_of("heading")}
    assert "Kapitel Eins" in headings
    assert "Kapitel Zwei" in headings
    assert headings["Kapitel Eins"] < headings["Kapitel Zwei"] or headings["Kapitel Eins"] == 1


def test_running_header_is_removed(document) -> None:
    joined = " ".join(b.text for b in document.blocks)
    assert HEADER not in joined


def test_paragraph_joins_lines_and_repairs_hyphenation(document) -> None:
    paragraphs = [b.text for b in document.blocks_of("paragraph")]
    assert any("Verwendung von Grundstoffen" in text for text in paragraphs)


def test_list_block_collects_items(document) -> None:
    lists = document.blocks_of("list")
    assert lists, "expected at least one list block"
    items = lists[0].list_items
    assert len(items) >= 2
    assert not lists[0].text.startswith("\u2022")


def test_table_block_has_cell_grid(document) -> None:
    tables = document.blocks_of("table")
    assert tables, "expected a table"
    cells = tables[0].cells
    assert len(cells) >= 2
    assert "Betriebsart" in cells[0]


def test_footnote_is_detected(document) -> None:
    notes = document.blocks_of("footnote")
    assert notes and "interne Messung" in notes[0].text


def test_two_column_reading_order(document) -> None:
    page2 = " ".join(b.text for b in document.blocks if b.page == 2)
    assert page2.index("linke Spaltentext") < page2.index("rechte Spaltentext")


def test_cross_references_found(document) -> None:
    kinds = {(r.kind, r.label) for r in document.cross_references}
    assert ("table", "2") in kinds
    assert ("section", "4.2") in kinds


def test_page_numbers_are_metadata(document) -> None:
    assert document.page_count == 3
    assert all(b.page >= 1 for b in document.blocks)


def test_inspect_report_prints_sections(document) -> None:
    report = format_inspect(document)
    assert "Outline:" in report
    assert "Block counts:" in report
    assert "Cross-references" in report
