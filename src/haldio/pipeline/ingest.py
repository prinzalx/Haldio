"""Stage S1: store the uploaded PDF and read its basic facts."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

import pymupdf

PDF_MAGIC = b"%PDF-"


@dataclass
class IngestResult:
    """What stage S1 writes and later stages read."""

    path: Path
    sha256: str
    page_count: int = 0
    title: str = ""
    author: str = ""
    is_pdf: bool = False
    has_text_layer: bool = False
    error: str = ""

    @property
    def ok(self) -> bool:
        return self.is_pdf and self.has_text_layer and not self.error


def compute_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def check_magic(path: Path) -> bool:
    """Accept a file only when it starts like a real PDF."""
    with path.open("rb") as handle:
        return handle.read(5) == PDF_MAGIC


def ingest(pdf_path: Path) -> IngestResult:
    """Read identity and structure facts. OCR is out of scope for version 1."""
    result = IngestResult(path=pdf_path, sha256=compute_sha256(pdf_path))
    if not check_magic(pdf_path):
        result.error = "not a PDF file (magic bytes)"
        return result
    result.is_pdf = True
    try:
        doc = pymupdf.open(pdf_path)
    except pymupdf.FileDataError:
        result.error = "broken PDF file"
        return result
    try:
        result.page_count = doc.page_count
        meta = doc.metadata or {}
        result.title = str(meta.get("title") or "").strip()
        result.author = str(meta.get("author") or "").strip()
        chars = sum(len(doc[i].get_text()) for i in range(min(doc.page_count, 5)))
        result.has_text_layer = chars > 0
    finally:
        doc.close()
    if not result.has_text_layer:
        result.error = "no text layer (OCR is out of scope for version 1)"
    return result
