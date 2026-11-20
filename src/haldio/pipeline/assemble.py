"""Stage S7: join editor results into the script and the QA report data."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from haldio.pipeline.editor_output import ChunkEdit


def _spoken_text(edit: ChunkEdit) -> list[dict[str, Any]]:
    if edit.result is None:
        return []
    return [block.model_dump() for block in edit.result.blocks]


def assemble_script(edits: list[ChunkEdit]) -> tuple[str, dict[str, Any]]:
    """Return (script.md text, script.json data) from ordered chunk edits."""
    markdown: list[str] = []
    script_chunks: list[dict[str, Any]] = []
    for edit in edits:
        blocks = _spoken_text(edit)
        warning_types = []
        if edit.result is not None:
            warning_types = [w.type for w in edit.result.warnings]
        if edit.needs_review or edit.error:
            warning_types.append("needs_review")
        script_chunks.append(
            {
                "chunk_id": edit.chunk_id,
                "blocks": blocks,
                "warnings": warning_types,
                "needs_review": edit.needs_review,
            }
        )
        for block in blocks:
            if block["kind"] == "heading":
                markdown.append("#" * int(block.get("level") or 1) + " " + block["text"])
            else:
                markdown.append(block["text"])
    script_md = "\n\n".join(markdown) + "\n"
    data = {
        "chunks": script_chunks,
        "chapter_ids": sorted({c["chunk_id"] for c in script_chunks}),
        "warnings": [w for c in script_chunks for w in c["warnings"]],
    }
    return script_md, data


def render_script_md(chunks: list[dict]) -> str:
    """Markdown for script.json chunk data (headings by level, else plain text)."""
    markdown = []
    for chunk in chunks:
        for block in chunk.get("blocks", []):
            if block.get("kind") == "heading":
                markdown.append("#" * int(block.get("level") or 1) + " " + block.get("text", ""))
            else:
                markdown.append(block.get("text", ""))
    return "\n\n".join(markdown) + "\n"


def write_script(out_dir: Path, script_md: str, data: dict[str, Any]) -> None:
    script_dir = out_dir / "04_script"
    script_dir.mkdir(parents=True, exist_ok=True)
    (script_dir / "script.md").write_text(script_md, encoding="utf-8")
    (script_dir / "script.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
