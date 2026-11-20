"""Stage S3: build the document map (doc_map.json).

Code does the structure first. The LLM only adds terms when asked.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from haldio.extract.model import Block, Document

# Patterns from the brief: CamelCase, ALL CAPS, words with digits, quoted terms, code spans.
_TERM_PATTERNS = [
    re.compile(r"\b[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+\b"),
    re.compile(r"\b(?![A-Z]{1,2}\b)[A-Z][A-Z0-9]{2,}\b"),
    re.compile(r"\b[A-Za-z][A-Za-z0-9]*(?:[-_./][A-Za-z0-9]+)*[0-9]+[A-Za-z0-9]*\b"),
    re.compile(r"(?:\"|“)([^\"”]{2,40})(?:\"|”)"),
    re.compile(r"`([^`]{2,40})`"),
]

_STOP_TERMS = {
    "Seite",
    "Page",
    "Tabelle",
    "Table",
    "Abbildung",
    "Figure",
    "Abschnitt",
    "Section",
    "Kapitel",
    "Chapter",
    "Anhang",
    "Beispiel",
    "Example",
    "Bild",
    " Nummer",
}


@dataclass
class ChapterNode:
    """One node of the chapter tree."""

    id: str
    title: str
    level: int
    page: int
    children: list[ChapterNode] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "level": self.level,
            "page": self.page,
            "children": [child.to_dict() for child in self.children],
        }


def find_protected_terms(blocks: list[Block]) -> list[str]:
    """Find product names, acronyms and technical terms with patterns."""
    counts: dict[str, int] = {}
    for block in blocks:
        if block.type == "code":
            continue
        for pattern in _TERM_PATTERNS:
            for match in pattern.finditer(block.text):
                term = match.group(1) if match.lastindex else match.group(0)
                term = term.strip(" .,;:")
                if len(term) < 2 or term in _STOP_TERMS or term.isdigit():
                    continue
                counts[term] = counts.get(term, 0) + 1
    ordered = sorted(counts, key=lambda t: (-counts[t], t))
    return ordered[:80]


def build_chapter_tree(document: Document) -> list[ChapterNode]:
    """Turn the heading blocks into a tree with stable ids."""
    roots: list[ChapterNode] = []
    stack: list[ChapterNode] = []
    counter = 0
    for block in document.blocks:
        if block.type != "heading":
            continue
        counter += 1
        node = ChapterNode(
            id=f"ch{counter:03d}",
            title=block.text,
            level=block.level or 1,
            page=block.page,
        )
        while stack and stack[-1].level >= node.level:
            stack.pop()
        if stack:
            stack[-1].children.append(node)
        else:
            roots.append(node)
        stack.append(node)
    return roots


def build_reference_index(document: Document) -> dict[str, dict[str, str]]:
    """Map each reference label to the block that holds its target."""
    index: dict[str, dict[str, str]] = {}
    targets = _target_labels(document.blocks)
    for reference in document.cross_references:
        key = f"{reference.kind}:{reference.label}"
        target_id = targets.get(key)
        index[key] = {
            "kind": reference.kind,
            "label": reference.label,
            "target_block_id": target_id or "",
            "target_caption": _caption_of(document.blocks, target_id),
            "source_block_id": reference.source_block_id,
            "page": str(reference.page),
        }
        if target_id:
            reference.target_block_id = target_id
    return index


def _target_labels(blocks: list[Block]) -> dict[str, str]:
    """Find blocks that define a table, figure or section number."""
    found: dict[str, str] = {}
    number = re.compile(r"^\s*([0-9]+(?:[.,][0-9]+)*)\s+(.+)", re.DOTALL)
    for block in blocks:
        if block.type == "table":
            label = re.match(r"^\s*(?:tabelle|table)\s*([0-9]+[a-z]?)", block.text, re.I)
            if label:
                found.setdefault(f"table:{label.group(1)}", block.id)
        elif block.type == "figure_caption":
            label = re.match(
                r"^\s*(?:abbildung|figur|figure|fig\.)\s*([0-9]+[a-z]?)", block.text, re.I
            )
            if label:
                found.setdefault(f"figure:{label.group(1)}", block.id)
        elif block.type == "heading":
            match = number.match(block.text)
            if match:
                found.setdefault(f"section:{match.group(1)}", block.id)
    return found


def _caption_of(blocks: list[Block], block_id: str | None) -> str:
    if not block_id:
        return ""
    for block in blocks:
        if block.id == block_id:
            return block.text[:120]
    return ""


def estimate_audio_seconds(document: Document, words_per_minute: int = 130) -> int:
    """Rough estimate of the spoken length."""
    words = sum(len(block.text.split()) for block in document.blocks)
    return int(words / words_per_minute * 60)


def build_doc_map(
    document: Document, summary: str = "", topics: list[str] | None = None
) -> dict[str, Any]:
    """Assemble the full doc_map structure."""
    return {
        "title": document.title,
        "author": document.author,
        "language": document.language,
        "page_count": document.page_count,
        "chapters": [chapter.to_dict() for chapter in build_chapter_tree(document)],
        "reference_index": build_reference_index(document),
        "protected_terms": find_protected_terms(document.blocks),
        "summary": summary,
        "main_topics": topics or [],
        "estimated_audio_seconds": estimate_audio_seconds(document),
    }
