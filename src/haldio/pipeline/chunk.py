"""Stage S4: split the document into chunks by structure.

Never cut inside a table, list, formula or code block. Prefer section borders.
"""

from __future__ import annotations

from typing import Any

from haldio.extract.model import Block, Document
from haldio.pipeline.plan import find_protected_terms

_NO_SPLIT = {"table", "list", "formula", "code", "figure_caption"}
_HEADING_DEPTH = 3


def _estimate_tokens(blocks: list[Block]) -> int:
    return sum(len(b.text) for b in blocks) // 4


def _chapter_path(path: list[str]) -> str:
    return " > ".join(path) if path else "(no chapter)"


def make_chunks(
    document: Document,
    max_tokens: int = 1500,
    policies: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Build chunk inputs with their context fields."""
    policies = policies or {}
    all_terms = set(find_protected_terms(document.blocks))
    chunks: list[dict[str, Any]] = []
    current: list[Block] = []
    path: list[str] = []
    title = document.title

    def flush() -> None:
        if not current:
            return
        texts = " ".join(b.text for b in current)
        terms = sorted(term for term in all_terms if term in texts)
        chunk_blocks = []
        for block in current:
            entry: dict[str, Any] = {"type": block.type, "text": block.text}
            if block.type == "heading":
                entry["level"] = block.level
            if block.cells:
                entry["cells"] = block.cells
            chunk_blocks.append(entry)
        chunks.append(
            {
                "chunk_id": f"c{len(chunks) + 1:04d}",
                "title": title,
                "chapter_path": _chapter_path(path),
                "protected_terms": terms,
                "resolved_references": [],
                "previous_script_tail": "",
                "policies": policies,
                "blocks": chunk_blocks,
                "page_span": [current[0].page, current[-1].page],
            }
        )
        current.clear()

    for block in document.blocks:
        if block.type == "heading" and (block.level or 1) <= _HEADING_DEPTH:
            flush()
            level = block.level or 1
            del path[level - 1 :]
            while len(path) < level - 1:
                path.append("")
            path.append(block.text)
        would_exceed = _estimate_tokens(current + [block]) > max_tokens
        if would_exceed and current and block.type not in _NO_SPLIT:
            flush()
        current.append(block)
        if would_exceed and current and block.type in _NO_SPLIT:
            flush()
    flush()
    return chunks
