"""S4 chunk output types."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, Field


class SpokenBlock(BaseModel):
    """One block in the editor's output."""

    kind: Literal["heading", "paragraph"]
    level: int | None = None
    text: str = ""


class EditorWarning(BaseModel):
    """A warning from the editor about a difficult source passage."""

    type: Literal[
        "table_large",
        "formula_complex",
        "code_omitted",
        "ambiguous_reference",
        "unclear_source",
        "other",
    ]
    detail: str = ""


class EditorResult(BaseModel):
    """The full answer from the editor for one chunk."""

    blocks: list[SpokenBlock] = Field(default_factory=list)
    warnings: list[EditorWarning] = Field(default_factory=list)
    unresolved_references: list[str] = Field(default_factory=list)


@dataclass
class ChunkEdit:
    """Editor output for one chunk plus retry bookkeeping."""

    chunk_id: str
    result: EditorResult | None
    attempts: int = 1
    error: str = ""
    needs_review: bool = False


EDITOR_JSON_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "blocks": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["heading", "paragraph"]},
                    "level": {"type": ["integer", "null"]},
                    "text": {"type": "string"},
                },
                "required": ["kind", "text"],
                "additionalProperties": False,
            },
        },
        "warnings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "type": {
                        "type": "string",
                        "enum": [
                            "table_large",
                            "formula_complex",
                            "code_omitted",
                            "ambiguous_reference",
                            "unclear_source",
                            "other",
                        ],
                    },
                    "detail": {"type": "string"},
                },
                "required": ["type", "detail"],
                "additionalProperties": False,
            },
        },
        "unresolved_references": {
            "type": "array",
            "items": {"type": "string"},
        },
    },
    "required": ["blocks", "warnings", "unresolved_references"],
    "additionalProperties": False,
}
