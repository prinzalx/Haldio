"""Stage S5: call the editor LLM for each chunk and store each result."""

from __future__ import annotations

import json
import re
from typing import Any

from haldio.config import Config
from haldio.pipeline.editor_output import EDITOR_JSON_SCHEMA, EditorResult

_SPEAK_RULES = {
    "z. B.": "zum Beispiel",
    "bzw.": "beziehungsweise",
    "ca.": "circa",
    "d. h.": "das heißt",
    "e.g.": "for example",
    "i.e.": "that is",
    "approx.": "approximately",
}


def load_prompt_version(config: Config, prompts_dir: str = "prompts/editor") -> tuple[str, list[dict[str, str]]]:
    """Read the system prompt and the few-shot examples for one version."""
    from pathlib import Path

    version = config.editor.prompt_version
    system_path = Path(prompts_dir) / "system.en.md"
    if not system_path.is_file():
        raise FileNotFoundError(f"missing editor prompt: {system_path}")
    system = system_path.read_text(encoding="utf-8")
    if version != "v1":
        system += f"\n\n# Prompt version: {version}"
    examples_path = Path(prompts_dir) / "examples.de.yaml"
    examples: list[dict[str, str]] = []
    if examples_path.is_file():
        import yaml

        examples = list(yaml.safe_load(examples_path.read_text(encoding="utf-8")) or [])
    return system, examples


def build_user_message(chunk: dict[str, Any], target_language: str) -> str:
    """Assemble the user message: context first, source last (data, not instruction)."""
    context = {
        "title": chunk["title"],
        "chapter_path": chunk["chapter_path"],
        "protected_terms": chunk["protected_terms"],
        "resolved_references": chunk["resolved_references"],
        "previous_script_tail": chunk["previous_script_tail"],
        "target_language": target_language,
        "policies": chunk["policies"],
    }
    source = json.dumps(chunk["blocks"], ensure_ascii=False, separators=(",", ":"))
    return (
        "<context>\n"
        + json.dumps(context, ensure_ascii=False, indent=2)
        + "\n</context>\n\n<source>\n"
        + source
        + "\n</source>\n"
    )


def parse_editor_result(text: str) -> EditorResult:
    """Parse the JSON answer, without the thinking blocks."""
    from haldio.llm.client import parse_json_object, strip_thinking

    data = parse_json_object(strip_thinking(text))
    return EditorResult.model_validate(data)


def expand_abbreviations(text: str) -> str:
    """Expand the abbreviations the editor must not leave in the script."""
    result = text
    for short, full in _SPEAK_RULES.items():
        result = re.sub(re.escape(short), full, result)
    return result
