"""Tests for stage S1 ingest."""

from __future__ import annotations

from pathlib import Path

import pytest
from reportlab.lib.pagesizes import A4

from haldio.pipeline.ingest import check_magic, compute_sha256, ingest
from synthetic import make_test_pdf


@pytest.fixture()
def pdf(tmp_path: Path) -> Path:
    return make_test_pdf(tmp_path / "test.pdf")


def test_sha256_is_stable(tmp_path: Path) -> None:
    path = tmp_path / "a.bin"
    path.write_bytes(b"hallo")
    assert compute_sha256(path) == compute_sha256(path)
    assert len(compute_sha256(path)) == 64


def test_magic_bytes_reject_other_files(tmp_path: Path) -> None:
    path = tmp_path / "a.txt"
    path.write_bytes(b"not a pdf")
    assert not check_magic(path)


def test_ingest_reads_pages_and_text_layer(pdf: Path) -> None:
    result = ingest(pdf)
    assert result.is_pdf
    assert result.has_text_layer
    assert result.page_count == 3
    assert result.ok


def test_ingest_stops_on_missing_text_layer(tmp_path: Path) -> None:
    """A PDF page without any text must stop with a clear message (OCR is out of scope)."""
    from reportlab.pdfgen import canvas

    empty = tmp_path / "scan.pdf"
    c = canvas.Canvas(str(empty), pagesize=A4)
    c.rect(50, 50, 300, 400, stroke=1, fill=0)
    c.showPage()
    c.save()
    result = ingest(empty)
    assert result.is_pdf
    assert not result.ok
    assert "no text layer" in result.error
