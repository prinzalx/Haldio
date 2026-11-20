"""Text report for `haldio inspect` (brief section 7)."""

from __future__ import annotations

from haldio.extract.model import Document


def format_inspect(document: Document) -> str:
    """Build the console report a user checks structure with."""
    lines: list[str] = []
    title = document.title or "(no title)"
    author = document.author or "(no author)"
    lines.append(f"Title:    {title}")
    lines.append(f"Author:   {author}")
    lines.append(f"Language: {document.language}")
    lines.append(f"Pages:    {document.page_count}")

    lines.append("")
    lines.append("Outline:")
    headings = document.blocks_of("heading")
    if headings:
        for block in headings:
            indent = "  " * max(0, (block.level or 1) - 1)
            lines.append(f"  {indent}{block.level}. {block.text}  [p{block.page}]")
    else:
        lines.append("  (none)")

    lines.append("")
    lines.append("Block counts:")
    counts: dict[str, int] = {}
    for block in document.blocks:
        counts[block.type] = counts.get(block.type, 0) + 1
    for name in sorted(counts):
        lines.append(f"  {name:<16} {counts[name]}")

    tables = document.blocks_of("table")
    lines.append("")
    lines.append(f"Tables ({len(tables)}):")
    for block in tables:
        rows = len(block.cells)
        cols = max((len(row) for row in block.cells), default=0)
        lines.append(f"  {block.id} p{block.page}: {rows} x {cols} cells={block.table_size}")

    references = document.cross_references
    lines.append("")
    lines.append(f"Cross-references ({len(references)}):")
    for reference in references[:40]:
        target = reference.target_block_id or "unresolved"
        lines.append(f"  {reference.kind} '{reference.label}' on p{reference.page} -> {target}")
    if len(references) > 40:
        lines.append(f"  ... {len(references) - 40} more")

    if document.warnings:
        lines.append("")
        lines.append("Warnings:")
        for warning in document.warnings:
            lines.append(f"  {warning}")
    return "\n".join(lines)
