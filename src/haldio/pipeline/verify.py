"""Stage S6: automatic checks on one editor result.

Failed checks become feedback for a retry. Warnings do not stop a chunk.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from haldio.pipeline.editor_output import EditorResult

_MARKUP = re.compile(r"(\*\*|\*|__|^#|\|\s|```|\[\d+\])", re.MULTILINE)
_MIN_RATIO = 0.8
_MAX_RATIO = 2.5


@dataclass
class Issue:
    """One verification finding."""

    severity: str  # "error" or "warning"
    rule: str
    detail: str

    @property
    def is_error(self) -> bool:
        return self.severity == "error"


def _spoken_digits_present(source: str, output: str) -> list[str]:
    """Digit strings of the source that appear in neither form in the output."""
    missing = []
    for digits in set(re.findall(r"\b\d+(?:[.,]\d+)*\b", source)):
        if digits in output:
            continue
        missing.append(digits)
    return missing


def verify_chunk(
    source_blocks: list[dict],
    result: EditorResult,
    protected_terms: list[str],
    target_language: str,
) -> list[Issue]:
    """Run all checks. Returns issues; empty list means the chunk is clean."""
    output = " ".join(block.text for block in result.blocks)
    source_text = " ".join(str(b.get("text", "")) for b in source_blocks)
    issues: list[Issue] = []

    for term in protected_terms:
        if term not in output:
            issues.append(Issue("error", "protected_term", term))

    for digits in _spoken_digits_present(source_text, output):
        issues.append(Issue("warning", "digits", digits))

    ratio = len(output) / max(1, len(source_text))
    if not _MIN_RATIO <= ratio <= _MAX_RATIO:
        issues.append(Issue("warning", "length_ratio", f"{ratio:.2f}"))

    if _MARKUP.search(output):
        issues.append(Issue("error", "markup", "markdown or table pipes left"))

    if target_language == "de" and re.search(r"\b(?:the|and|with)\b", output, re.I):
        issues.append(Issue("warning", "language", "english words in german output"))
    if target_language == "en" and re.search(r"\b(?:und|nicht|mit)\b", output, re.I):
        issues.append(Issue("warning", "language", "german words in english output"))

    return issues
