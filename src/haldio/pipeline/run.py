"""CLI pipeline S1..S7: PDF in, script.md + QA report out (stage S8+ come in M3)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from haldio.config import Config, TtsConfig
from haldio.extract import PyMuPDFExtractor
from haldio.llm import LlmClient
from haldio.llm.client import llm_reachable
from haldio.pipeline.assemble import assemble_script, write_script
from haldio.pipeline.chunk import make_chunks
from haldio.pipeline.edit import (
    build_user_message,
    load_prompt_version,
    parse_editor_result,
    system_with_examples,
)
from haldio.pipeline.editor_output import EDITOR_JSON_SCHEMA, ChunkEdit
from haldio.pipeline.ingest import ingest
from haldio.pipeline.master import MasterResult, make_master
from haldio.pipeline.plan import build_doc_map
from haldio.pipeline.qa_report import ChunkQA, render_qa_html, write_qa_report
from haldio.pipeline.speak import SpeakResult, synthesize_script
from haldio.pipeline.verify import Issue, verify_chunk
from haldio.tts import TTSBackend, create_backend
from haldio.tts.normalizer import load_pronunciations


@dataclass
class ScriptResult:
    """Outcome of the script pipeline."""

    out_dir: Path
    chunks: int = 0
    needs_review: int = 0
    errors: int = 0
    warnings: int = 0
    error: str = ""
    language: str = "de"
    doc_meta: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def return_code(self) -> int:
        return 1 if self.error else 0

    def summary(self) -> str:
        if self.error:
            return f"script failed: {self.error}"
        return (
            f"script: {self.chunks} chunks -> {self.out_dir / '04_script' / 'script.md'}\n"
            f"QA: {self.errors} errors, {self.warnings} warnings, "
            f"{self.needs_review} need review"
        )


def cache_key(payload: object, prompt_version: str, model_id: str) -> str:
    """Hash of (input, prompt version, model id) — the brief's editor cache key."""
    blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    raw = f"{blob}|{prompt_version}|{model_id}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _run_hook(name: str, command: str) -> None:
    """Optional shell hook around a stage (e.g. 'lms unload --all')."""
    if not command.strip():
        return
    import subprocess

    done = subprocess.run(command, shell=True, capture_output=True, text=True)
    if done.returncode != 0:
        print(f"hook {name} failed ({done.returncode}): {done.stderr.strip()[:200]}")


def _before_speak(config: Config, gate: Callable[[str], None] | None) -> None:
    """Model swap before S8: run the hook, or wait for the user when it is empty."""
    if config.hooks.before_speak.strip():
        _before_speak(config, gate)
    elif gate:
        gate("LLM stoppen, dann Weiter drücken.")


def edit_chunk_with_retry(
    chunk: dict[str, Any],
    client: LlmClient,
    system_prompt: str,
    target_language: str,
    max_retries: int,
) -> tuple[ChunkEdit, list[Issue]]:
    """Call the editor, verify, and retry with the issues as feedback."""
    feedback = ""
    issues: list[Issue] = []
    best: ChunkEdit | None = None
    for attempt in range(max_retries + 1):
        user = build_user_message(chunk, target_language) + feedback
        answer = client.chat(system_prompt, user, json_schema=EDITOR_JSON_SCHEMA)
        try:
            result = parse_editor_result(answer.text)
        except Exception as error:  # noqa: BLE001 - any bad answer triggers a retry
            feedback = f"\n\nPrevious answer was invalid: {error}. Return valid JSON only."
            continue
        if not result.blocks:
            feedback = (
                "\n\nPrevious answer had an empty blocks array. "
                'Return {"blocks": [...]} with the spoken blocks.'
            )
            continue
        issues = verify_chunk(chunk["blocks"], result, chunk["protected_terms"], target_language)
        best = ChunkEdit(chunk_id=chunk["chunk_id"], result=result, attempts=attempt + 1)
        if not any(i.is_error for i in issues):
            return best, issues
        names = ", ".join(sorted({i.rule for i in issues if i.is_error}))
        feedback = f"\n\nFix these issues: {names}."
    if best is None:
        best = ChunkEdit(chunk_id=chunk["chunk_id"], result=None, attempts=max_retries + 1)
    best.needs_review = True
    return best, issues


def run_script(
    pdf_path: Path,
    config: Config,
    out_dir: Path,
    client_factory: Callable[[], LlmClient] | None = None,
    progress: Callable[[str, int], None] | None = None,
) -> ScriptResult:
    """Run S1..S7 and write the job folder layout."""
    report = progress or (lambda _stage, _value: None)
    ingested = ingest(pdf_path)
    if not ingested.ok:
        return ScriptResult(out_dir=out_dir, error=ingested.error)

    report("extracting", 5)
    out_dir.mkdir(parents=True, exist_ok=True)
    document = PyMuPDFExtractor().extract(pdf_path)
    _write_json(out_dir / "01_extract" / "document.json", document.to_dict())

    doc_map = build_doc_map(document)
    _write_json(out_dir / "02_plan" / "doc_map.json", doc_map)

    target_language = document.language if document.language in ("de", "en") else "de"
    chunks = make_chunks(document, config.llm.max_input_tokens, dict(config.policies))

    system_prompt, examples = load_prompt_version(config)
    system_prompt = system_with_examples(system_prompt, examples)
    client = client_factory() if client_factory else LlmClient(config.llm)
    edits: list[ChunkEdit] = []
    qa: list[ChunkQA] = []
    previous_tail = ""
    _run_hook("before_edit", config.hooks.before_edit)
    try:
        for index, chunk in enumerate(chunks):
            report("editing", 10 + int(50 * index / max(1, len(chunks))))
            chunk["previous_script_tail"] = previous_tail
            edit, issues = edit_chunk_with_retry(
                chunk, client, system_prompt, target_language, config.editor.max_retries
            )
            edits.append(edit)
            qa.append(
                ChunkQA(chunk_id=chunk["chunk_id"], issues=issues, needs_review=edit.needs_review)
            )
            _write_json(out_dir / "03_edit" / "chunks" / f"{chunk['chunk_id']}.in.json", chunk)
            if edit.result is not None:
                _write_json(
                    out_dir / "03_edit" / "chunks" / f"{chunk['chunk_id']}.out.json",
                    edit.result.model_dump(),
                )
                spoken = " ".join(b.text for b in edit.result.blocks)
                previous_tail = " ".join(spoken.split()[-20:])
    finally:
        if client_factory is None:
            client.close()
    _run_hook("after_edit", config.hooks.after_edit)

    _write_json(out_dir / "03_edit" / "qa.json", [asdict(c) for c in qa])
    script_md, data = assemble_script(edits)
    write_script(out_dir, script_md, data)
    write_qa_report(out_dir, render_qa_html(qa, doc_map))

    return ScriptResult(
        out_dir=out_dir,
        chunks=len(chunks),
        needs_review=sum(1 for e in edits if e.needs_review),
        errors=sum(1 for c in qa if c.errors),
        warnings=sum(len(c.warnings) for c in qa),
        language=target_language,
        doc_meta=doc_map,
    )


@dataclass
class BookResult:
    """Outcome of the full S1..S9 pipeline."""

    script: ScriptResult
    speak: SpeakResult
    master: MasterResult
    review_paused: bool = False
    tts_gate: bool = False

    @property
    def return_code(self) -> int:
        return 1 if (self.script.error or self.speak.error or self.master.error) else 0

    def summary(self) -> str:
        parts = [self.script.summary()]
        if not self.speak.error:
            parts.append(f"speak: {self.speak.synthesized} synthesized, {self.speak.cached} cached")
        elif self.speak.error:
            parts.append(f"speak failed: {self.speak.error}")
        if self.master.ok:
            names = ", ".join(f.name for f in self.master.files)
            parts.append(f"master: {names}")
        elif self.master.error:
            parts.append(f"master: {self.master.error}")
        return "\n".join(parts)


def run_book(
    pdf_path: Path,
    config: Config,
    out_dir: Path,
    client_factory: Callable[[], LlmClient] | None = None,
    backend_factory: Callable[[TtsConfig], TTSBackend] | None = None,
    pronunciations_path: Path | None = None,
    progress: Callable[[str, int], None] | None = None,
    stop_after_script: bool = False,
    stop_before_tts: bool = False,
    gate: Callable[[str], None] | None = None,
) -> BookResult:
    """Run S1..S9: PDF in, script, unit audio and master files out.

    stop_after_script pauses at the review gate; stop_before_tts pauses in the
    ready2tts pool so the user can free memory before the TTS worker starts.
    gate(note) blocks the stage until the user presses Continue (manual model swap).
    """
    report = progress or (lambda _stage, _value, _note="": None)
    if gate and not llm_reachable(config.llm):
        gate("LLM starten, dann Weiter drücken.")
    script = run_script(pdf_path, config, out_dir, client_factory, progress)
    if not script.ok:
        return BookResult(script, SpeakResult(error=script.error), MasterResult())
    if stop_after_script:
        return BookResult(script, SpeakResult(), MasterResult(), review_paused=True)
    if stop_before_tts:
        return BookResult(script, SpeakResult(), MasterResult(), tts_gate=True)

    data = json.loads((out_dir / "04_script" / "script.json").read_text(encoding="utf-8"))
    report("speaking", 65)
    _before_speak(config, gate)
    backend = (backend_factory or create_backend)(config.tts)
    try:
        spoken = synthesize_script(
            data,
            backend,
            config.tts.backend,
            config.tts,
            out_dir,
            script.language,
            load_pronunciations(pronunciations_path or Path("pronunciations.yaml")),
            progress=lambda done, total: report(
                "speaking", 65 + int(20 * done / max(1, total)), f"{done}/{total}"
            ),
        )
    finally:
        backend.close()
    _run_hook("after_speak", config.hooks.after_speak)
    if not spoken.ok:
        return BookResult(script, spoken, MasterResult(error=spoken.error))

    report("mastering", 90)
    master = make_master(
        out_dir,
        config.audio.formats,
        config.audio.pause_ms.model_dump(),
        config.audio.mp3_bitrate_kbps,
    )
    return BookResult(script, spoken, master)


def run_speech(
    out_dir: Path,
    config: Config,
    language: str,
    backend_factory: Callable[[TtsConfig], TTSBackend] | None = None,
    pronunciations_path: Path | None = None,
    progress: Callable[..., None] | None = None,
    gate: Callable[[str], None] | None = None,
) -> BookResult:
    """Run only S8 and S9 for a job whose script.json already exists (after review)."""
    report = progress or (lambda *_a: None)
    script = ScriptResult(out_dir=out_dir, chunks=0, language=language)
    data = json.loads((out_dir / "04_script" / "script.json").read_text(encoding="utf-8"))
    report("speaking", 65)
    _before_speak(config, gate)
    backend = (backend_factory or create_backend)(config.tts)
    try:
        spoken = synthesize_script(
            data,
            backend,
            config.tts.backend,
            config.tts,
            out_dir,
            language,
            load_pronunciations(pronunciations_path or Path("pronunciations.yaml")),
            progress=lambda done, total: report(
                "speaking", 65 + int(20 * done / max(1, total)), f"{done}/{total}"
            ),
        )
    finally:
        backend.close()
    _run_hook("after_speak", config.hooks.after_speak)
    if not spoken.ok:
        return BookResult(script, spoken, MasterResult(error=spoken.error))
    report("mastering", 90)
    master = make_master(
        out_dir,
        config.audio.formats,
        config.audio.pause_ms.model_dump(),
        config.audio.mp3_bitrate_kbps,
    )
    return BookResult(script, spoken, master)
