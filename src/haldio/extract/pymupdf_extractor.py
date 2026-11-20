"""PyMuPDF extractor: page lines to a structured block model (stage S2)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from statistics import median

import pymupdf

from haldio.extract.model import Block
from haldio.extract.text_clean import (
    join_lines,
    list_marker,
    strip_list_marker,
)

_HEADING_RATIO = 1.10
_SMALL_RATIO = 0.86
_MIN_PAGE_SHARE = 0.5


@dataclass
class Line:
    """One text line with the style we need for classification."""

    text: str
    bbox: tuple[float, float, float, float]
    size: float
    bold: bool
    mono: bool
    superscript: bool
    page: int

    @property
    def width(self) -> float:
        return self.bbox[2] - self.bbox[0]


def _page_lines(page: pymupdf.Page, page_no: int) -> list[Line]:
    lines: list[Line] = []
    data = page.get_text("dict")
    for block in data["blocks"]:
        if block.get("type") != 0:
            continue
        for line in block["lines"]:
            spans = [s for s in line["spans"] if s.get("text", "").strip()]
            if not spans:
                continue
            text = "".join(s["text"] for s in spans)
            sizes = [s["size"] for s in spans]
            bold = any(s["flags"] & 2**4 for s in spans)
            mono = any("mono" in s["font"].lower() for s in spans)
            sup = any(s["flags"] & 2**3 for s in spans)
            bb = line["bbox"]
            lines.append(
                Line(text, (bb[0], bb[1], bb[2], bb[3]), max(sizes), bold, mono, sup, page_no)
            )
    return lines


def _normalise(text: str) -> str:
    return "".join("#" if ch.isdigit() else ch for ch in text.strip().lower())


def _page_number(text: str) -> bool:
    core = text.strip().strip("()").lower()
    return bool(core.replace(".", "").isdigit() or core in {"seite", "page"}) or (
        len(core) <= 8 and any(ch.isdigit() for ch in core) and " " not in core.strip(".")
    )


def detect_running_text(pages_lines: list[list[Line]], page_height: float) -> set[tuple[int, str]]:
    """Find header/footer lines by repetition across pages (brief section 7)."""
    if len(pages_lines) < 3:
        return set()
    top: dict[str, int] = {}
    bottom: dict[str, int] = {}
    for lines in pages_lines:
        seen_top = {_normalise(ln.text) for ln in lines if ln.bbox[1] < page_height * 0.09}
        seen_bottom = {_normalise(ln.text) for ln in lines if ln.bbox[3] > page_height * 0.90}
        for key in seen_top:
            top[key] = top.get(key, 0) + 1
        for key in seen_bottom:
            bottom[key] = bottom.get(key, 0) + 1
    limit = max(2, int(len(pages_lines) * _MIN_PAGE_SHARE))
    bad = {k for k, n in top.items() if n >= limit and k}
    bad |= {k for k, n in bottom.items() if n >= limit and k}
    drop: set[tuple[int, str]] = set()
    for page_index, lines in enumerate(pages_lines):
        for ln in lines:
            key = _normalise(ln.text)
            edge = ln.bbox[1] < page_height * 0.09 or ln.bbox[3] > page_height * 0.90
            if (key in bad and edge) or (_page_number(ln.text) and edge):
                drop.add((page_index, ln.text))
    return drop


def _by_y(line: Line) -> tuple[float, float]:
    return (line.bbox[1], line.bbox[0])


def _side_order(segment: list[Line], mid: float) -> list[Line]:
    left = [ln for ln in segment if (ln.bbox[0] + ln.bbox[2]) / 2 < mid]
    right = [ln for ln in segment if (ln.bbox[0] + ln.bbox[2]) / 2 >= mid]
    if left and right:
        return sorted(left, key=_by_y) + sorted(right, key=_by_y)
    return sorted(segment, key=_by_y)


def _column_mid(lines: list[Line], left_edge: float, content: float) -> float | None:
    """Find the gutter x from narrow lines only; full-width lines hide it."""
    body = [ln for ln in lines if ln.width < content * 0.6]
    if not body:
        return None
    bins = max(24, int(content))
    occupied = [False] * bins
    for line in body:
        start = int((line.bbox[0] - left_edge) / content * bins)
        end = int((line.bbox[2] - left_edge) / content * bins)
        for index in range(max(0, start), min(bins, end + 1)):
            occupied[index] = True
    best_start, best_run, run = -1, 0, 0
    for index, used in enumerate(occupied):
        if used:
            if run > best_run:
                best_start, best_run = index - run, run
            run = 0
        else:
            run += 1
    if run > best_run:
        best_start, best_run = bins - run, run
    if best_start < 0 or (best_run / bins) * content < max(8.0, content * 0.04):
        return None
    return left_edge + (best_start + best_run / 2) / bins * content


def split_columns(lines: list[Line]) -> list[Line]:
    """Order lines for single- or two-column pages (brief: correct reading order).

    A column border exists only where a real vertical gap is free of text. Each line
    is assigned to exactly one side, so no line can be lost. Full-width lines end a
    column zone, so a heading above two columns does not hide the gutter.
    """
    if not lines:
        return []
    left_edge = min(ln.bbox[0] for ln in lines)
    right_edge = max(ln.bbox[2] for ln in lines)
    content = right_edge - left_edge
    if content <= 1:
        return sorted(lines, key=_by_y)
    mid = _column_mid(lines, left_edge, content)
    if mid is None:
        return sorted(lines, key=_by_y)
    out: list[Line] = []
    segment: list[Line] = []
    for line in sorted(lines, key=_by_y):
        if line.width > content * 0.6:
            out.extend(_side_order(segment, mid))
            segment = []
            out.append(line)
        else:
            segment.append(line)
    out.extend(_side_order(segment, mid))
    return out


def _body_size(pages_lines: list[list[Line]]) -> float:
    sizes = [ln.size for lines in pages_lines for ln in lines for _ in range(max(1, len(ln.text)))]
    return median(sizes) if sizes else 12.0


def _toc_line(text: str) -> bool:
    return bool(re.search(r"\.{3,}\s*[0-9]+\s*$", text.strip()))


BBox = tuple[float, float, float, float]


def _table_cells(page: pymupdf.Page) -> list[tuple[BBox, list[list[str]]]]:
    """Return (bbox, cells) for every table found on the page."""
    out = []
    try:
        finder = page.find_tables()
    except Exception:  # pragma: no cover - depends on page content
        return out
    for table in finder.tables:
        cells = [[(c or "").strip() for c in row] for row in table.extract()]
        if cells:
            out.append((tuple(table.bbox), cells))
    return out


def _in_any_table(bbox: tuple[float, float, float, float], rects: list[tuple[float, ...]]) -> bool:
    x0, y0, x1, y1 = bbox
    return any(r[0] - 2 <= x0 and y0 >= r[1] - 2 and y1 <= r[3] + 2 for r in rects)


def _is_footnote(line: Line, body: float, page_height: float) -> bool:
    return line.size <= body * _SMALL_RATIO and line.bbox[1] > page_height * 0.75


def _is_code(lines: list[Line]) -> bool:
    return len(lines) > 1 and sum(1 for ln in lines if ln.mono) >= len(lines) * 0.6


def _gap(a: Line, b: Line) -> float:
    return b.bbox[1] - a.bbox[3]


def _flush_paragraph(lines: list[Line], out: list[Block]) -> None:
    if not lines:
        return
    text = join_lines([ln.text for ln in lines])
    if not text:
        return
    if _is_code(lines):
        kind: str = "code"
    elif len(text) < 160 and re.search(r"[^a-z]=[^a-z]|[∑·×±]", text) and not text.endswith("."):
        kind = "formula"
    else:
        kind = "paragraph"
    first = lines[0]
    out.append(
        Block(
            id=f"b{len(out) + 1:04d}",
            type=kind,  # type: ignore[arg-type]
            text=text,
            page=first.page,
            bbox=(first.bbox[0], first.bbox[1], lines[-1].bbox[2], lines[-1].bbox[3]),
        )
    )


def _classify_page(
    page: pymupdf.Page, page_no: int, body: float, drop: set[tuple[int, str]], page_height: float
) -> list[Block]:
    """Turn one page into blocks. Headings get a temporary level from font size."""
    lines = [ln for ln in _page_lines(page, page_no) if (page_no - 1, ln.text) not in drop]
    rects = _table_cells(page)
    ordered = split_columns(lines)
    toc_hits = sum(1 for ln in ordered if _toc_line(ln.text))
    is_toc_page = toc_hits >= max(3, int(len(ordered) * 0.4))
    out: list[Block] = []
    para: list[Line] = []
    inside = [rect for rect, _ in rects]
    next_table = 0
    for line in ordered:
        if next_table < len(rects) and line.bbox[1] >= rects[next_table][0][1]:
            rect, cells = rects[next_table]
            _flush_paragraph(para, out)
            para = []
            out.append(
                Block(
                    id=f"b{len(out) + 1:04d}",
                    type="table",
                    text=" ",
                    page=page_no,
                    bbox=rect,
                    cells=cells,
                    has_header_row=True,
                )
            )
            next_table += 1
        if _in_any_table(line.bbox, inside):
            continue
        heading = line.size >= body * _HEADING_RATIO or (line.bold and len(line.text) < 90)
        marker = list_marker(line.text)
        footnote = _is_footnote(line, body, page_height)
        boundary = heading or marker or footnote or (is_toc_page and _toc_line(line.text))
        if para and (boundary or _gap(para[-1], line) > max(6.0, para[-1].size * 1.9)):
            _flush_paragraph(para, out)
            para = []
        if heading:
            out.append(
                Block(
                    id=f"b{len(out) + 1:04d}",
                    type="heading",
                    text=line.text.strip(),
                    page=page_no,
                    level=0,
                    bbox=line.bbox,
                    size_hint=line.size,
                )
            )
        elif footnote:
            out.append(
                Block(
                    id=f"b{len(out) + 1:04d}",
                    type="footnote",
                    text=line.text.strip(),
                    page=page_no,
                    bbox=line.bbox,
                )
            )
        elif marker:
            out.append(
                Block(
                    id=f"b{len(out) + 1:04d}",
                    type="list",
                    text=strip_list_marker(line.text),
                    page=page_no,
                    bbox=line.bbox,
                    list_items=[{"text": strip_list_marker(line.text), "level": 0}],
                )
            )
        elif is_toc_page and _toc_line(line.text):
            out.append(
                Block(
                    id=f"b{len(out) + 1:04d}",
                    type="toc",
                    text=re.sub(r"\.{3,}\s*", " ", line.text.strip()),
                    page=page_no,
                    bbox=line.bbox,
                )
            )
        else:
            para.append(line)
    _flush_paragraph(para, out)
    return out
