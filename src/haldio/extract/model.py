"""Structured document model produced by the extractor (stage S2).

One block is one meaningful unit: a heading, a paragraph, a table, and so on.
Page numbers are metadata for quality checks only, never for the spoken text.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

BlockType = Literal[
    "heading",
    "paragraph",
    "list",
    "table",
    "figure_caption",
    "footnote",
    "code",
    "formula",
    "quote",
    "toc",
    "index",
    "bibliography",
]

REFERENCE_KIND = Literal["section", "table", "figure", "page", "other"]


@dataclass
class Block:
    """One unit of content inside the document."""

    id: str
    type: BlockType
    text: str = ""
    page: int = 0
    level: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    cells: list[list[str]] = field(default_factory=list)
    has_header_row: bool = False
    list_items: list[dict[str, Any]] = field(default_factory=list)
    footnote_marker: str = ""
    page_span: tuple[int, int] | None = None
    size_hint: float = 0.0

    @property
    def table_size(self) -> int:
        """Number of table cells, used by the table policy later."""
        return sum(len(row) for row in self.cells)


@dataclass
class CrossReference:
    """A reference in the text to another place in the document."""

    kind: REFERENCE_KIND
    label: str
    source_block_id: str
    page: int = 0
    target_block_id: str | None = None


@dataclass
class Document:
    """The whole extracted document."""

    title: str = ""
    author: str = ""
    page_count: int = 0
    language: str = "unknown"
    has_text_layer: bool = False
    blocks: list[Block] = field(default_factory=list)
    cross_references: list[CrossReference] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def blocks_of(self, block_type: BlockType) -> list[Block]:
        return [b for b in self.blocks if b.type == block_type]

    def to_dict(self) -> dict[str, Any]:
        """Plain data for document.json."""
        data = asdict(self)
        data["block_counts"] = {}
        for block in self.blocks:
            data["block_counts"][block.type] = data["block_counts"].get(block.type, 0) + 1
        return data
