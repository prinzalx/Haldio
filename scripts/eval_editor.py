"""Run the editor eval cases against the live LM Studio and print pass/fail.

Usage: uv run python scripts/eval_editor.py [path/to/editor_cases.yaml]
Exit code 1 when any case fails.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import yaml

from haldio.config import load_config
from haldio.extract.model import Block
from haldio.llm import LlmClient
from haldio.pipeline.edit import load_prompt_version, system_with_examples
from haldio.pipeline.plan import find_protected_terms
from haldio.pipeline.run import edit_chunk_with_retry

DEFAULT_CASES = Path("tests/eval/editor_cases.yaml")


def _block_text(block: dict[str, Any]) -> str:
    """All readable text of a source block, including table cells and list items."""
    parts = [str(block.get("text", ""))]
    for row in block.get("cells") or []:
        parts.extend(str(cell) for cell in row)
    for item in block.get("list_items") or []:
        parts.append(str(item.get("text", "")))
    return " ".join(part for part in parts if part.strip())


def _chunk_from_case(case: dict[str, Any]) -> tuple[dict[str, Any], str]:
    import json

    blocks = json.loads(case["source"])
    text = " ".join(_block_text(b) for b in blocks)
    return {
        "chunk_id": f"eval-{case['name']}",
        "title": "Eval",
        "chapter_path": "Eval",
        "protected_terms": find_protected_terms(
            [
                Block(id=f"e{i}", type="paragraph", text=str(b.get("text", "")), page=1)
                for i, b in enumerate(blocks)
            ]
        ),
        "resolved_references": [],
        "previous_script_tail": "",
        "policies": {},
        "blocks": blocks,
        "page_span": [1, 1],
    }, text


def main() -> int:
    cases_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_CASES
    cases = yaml.safe_load(cases_path.read_text(encoding="utf-8"))
    config = load_config(None)
    system, examples = load_prompt_version(config)
    system = system_with_examples(system, examples)
    client = LlmClient(config.llm)
    failed = 0
    try:
        for case in cases:
            chunk, source_text = _chunk_from_case(case)
            edit, _issues = edit_chunk_with_retry(
                chunk, client, system, "de", config.editor.max_retries
            )
            spoken = " ".join(b.text for b in (edit.result.blocks if edit.result else []))
            spoken_fold = spoken.casefold()
            problems: list[str] = []
            for needle in case.get("must_contain", []):
                if needle.casefold() not in spoken_fold:
                    problems.append(f"missing {needle!r}")
            for needle in case.get("must_not_contain", []):
                if needle in spoken:
                    problems.append(f"found {needle!r}")
            limit = case.get("max_length_ratio", 2.5)
            if source_text and len(spoken) > len(source_text) * limit:
                problems.append(f"too long (>{limit}x)")
            if edit.needs_review:
                problems.append("needs review")
            status = "PASS" if not problems else "FAIL"
            failed += 0 if not problems else 1
            print(f"{status} {case['name']}: {'; '.join(problems) or spoken[:80]}")
    finally:
        client.close()
    print(f"{len(cases) - failed}/{len(cases)} cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
