"""Extractor interface and the PyMuPDF implementation entry point."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import pymupdf

from haldio.extract.model import Block, CrossReference, Document
from haldio.extract.pymupdf_extractor import (
    _body_size,
    _classify_page,
    _page_lines,
    detect_running_text,
)
from haldio.extract.text_clean import find_cross_references

_DE_MARKERS = (" der ", " und ", " ist ", " nicht ", " mit ", " die ", " für ")
_EN_MARKERS = (" the ", " and ", " is ", " not ", " with ", " of ", " for ")


class Extractor(Protocol):
    """Stage S2 contract: a PDF path in, a Document out."""

    def extract(self, pdf_path: Path) -> Document: ...


def _detect_language(text: str) -> str:
    lower = text.lower()
    de = sum(lower.count(m) for m in _DE_MARKERS)
    en = sum(lower.count(m) for m in _EN_MARKERS)
    if de == en == 0:
        return "unknown"
    return "de" if de > en else "en"


def _merge_lists(blocks: list[Block]) -> list[Block]:
    """Join single-item list blocks that follow each other on the same page."""
    out: list[Block] = []
    for block in blocks:
        previous = out[-1] if out else None
        if (
            previous
            and block.type == "list"
            and previous.type == "list"
            and previous.page == block.page
        ):
            previous.text = f"{previous.text}; {block.text}"
            previous.list_items.extend(block.list_items)
            previous.bbox = (
                previous.bbox[0],
                previous.bbox[1],
                block.bbox[2],
                block.bbox[3],
            )
        else:
            out.append(block)
    return out


def _assign_heading_levels(blocks: list[Block], outline: list[list[object]]) -> None:
    """Use the PDF outline when it exists, otherwise rank headings by font size."""
    headings = [b for b in blocks if b.type == "heading"]
    if not headings:
        return
    title_map: dict[str, int] = {}
    for item in outline:
        title_map[str(item[1]).strip().lower()] = int(item[0])
    if title_map:
        for block in headings:
            block.level = title_map.get(block.text.strip().lower(), 1)
        return
    sizes = sorted({b.size_hint for b in headings}, reverse=True)
    rank = {size: index + 1 for index, size in enumerate(sizes)}
    for block in headings:
        block.level = min(rank.get(block.size_hint, 1), 6)


def _link_footnotes(blocks: list[Block]) -> None:
    """Give each footnote its marker and record it on the paragraph page."""
    markers = [b for b in blocks if b.type == "footnote"]
    for index, block in enumerate(markers, start=1):
        block.footnote_marker = str(index)


def _renumber(blocks: list[Block]) -> None:
    for index, block in enumerate(blocks, start=1):
        block.id = f"b{index:04d}"


_JUNK_META = {"", "untitled", "unbenannt", "anonymous", "none"}


def _find_title(blocks: list[Block], meta: dict[str, object]) -> tuple[str, str]:
    """Prefer real embedded metadata, fall back to the first level-1 heading."""
    title = str(meta.get("title") or "").strip()
    author = str(meta.get("author") or "").strip()
    if title.lower() in _JUNK_META:
        title = ""
    if author.lower() in _JUNK_META:
        author = ""
    if not title:
        for block in blocks:
            if block.type == "heading" and block.level == 1:
                title = block.text
                break
    return title, author


class PyMuPDFExtractor:
    """Build the block model with PyMuPDF (brief section 7, S2)."""

    name = "pymupdf"

    def extract(self, pdf_path: Path) -> Document:
        doc = pymupdf.open(pdf_path)
        try:
            pages_lines = [_page_lines(doc[i], i + 1) for i in range(doc.page_count)]
            total_chars = sum(len(ln.text) for lines in pages_lines for ln in lines)
            height = doc[0].rect.height if doc.page_count else 841.0
            drop = detect_running_text(pages_lines, height)
            body = _body_size(pages_lines)
            blocks: list[Block] = []
            for index, page in enumerate(doc):
                blocks.extend(_classify_page(page, index + 1, body, drop, page.rect.height))
            outline = doc.get_toc()
            meta = doc.metadata or {}
        finally:
            doc.close()

        blocks = _merge_lists(blocks)
        _assign_heading_levels(blocks, outline)
        _renumber(blocks)
        _link_footnotes(blocks)

        document = Document(
            page_count=len(pages_lines),
            has_text_layer=total_chars > 0,
            blocks=blocks,
            language=_detect_language(" ".join(b.text for b in blocks)),
        )
        document.title, document.author = _find_title(blocks, meta)
        references: list[CrossReference] = []
        for block in blocks:
            for kind, label in find_cross_references(block.text):
                references.append(
                    CrossReference(
                        kind=kind, label=label, source_block_id=block.id, page=block.page
                    )
                )
        document.cross_references = references
        if not document.has_text_layer:
            document.warnings.append("no text layer")
        return document
