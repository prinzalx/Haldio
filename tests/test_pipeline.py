"""Tests for chunking, verification and the plan stage."""

from __future__ import annotations

import pytest

from haldio.extract.model import Block, CrossReference, Document
from haldio.pipeline.chunk import make_chunks
from haldio.pipeline.editor_output import EditorResult, SpokenBlock
from haldio.pipeline.plan import (
    build_chapter_tree,
    build_doc_map,
    find_protected_terms,
    quick_summary,
)
from haldio.pipeline.verify import verify_chunk


def _doc() -> Document:
    blocks = [
        Block(id="b1", type="heading", text="Kapitel Eins", page=1, level=1),
        Block(id="b2", type="paragraph", text="Der CamelCaseWert und USB2 werden benutzt.", page=1),
        Block(id="b3", type="table", text="Tabelle", page=1, cells=[["a", "b"], ["1", "2"]]),
        Block(id="b4", type="heading", text="Unterkapitel", page=2, level=2),
        Block(id="b5", type="paragraph", text="Ein zweiter Absatz mit Text.", page=2),
    ]
    doc = Document(title="T", author="A", page_count=2, language="de", blocks=blocks)
    doc.cross_references = [CrossReference(kind="table", label="2", source_block_id="b2", page=1)]
    return doc


def test_protected_terms_find_identifiers() -> None:
    terms = find_protected_terms(_doc().blocks)
    assert "CamelCaseWert" in terms
    assert "USB2" in terms


def test_chapter_tree_nesting() -> None:
    tree = build_chapter_tree(_doc())
    assert len(tree) == 1
    assert tree[0].title == "Kapitel Eins"
    assert tree[0].children[0].title == "Unterkapitel"


def test_chunks_never_split_inside_table() -> None:
    chunks = make_chunks(_doc(), max_tokens=10)
    for chunk in chunks:
        types = [b["type"] for b in chunk["blocks"]]
        if "table" in types:
            # the table block stands alone or with a heading, never cut mid-table
            assert types.count("table") == 1
    assert sum(len(c["blocks"]) for c in chunks) == 5


def test_chunk_context_has_chapter_path() -> None:
    chunks = make_chunks(_doc(), max_tokens=1000)
    assert chunks[0]["chapter_path"].startswith("Kapitel Eins")


def test_chunk_keeps_table_cells_and_list_items() -> None:
    """Content stored outside the text field must survive into the chunk file."""
    doc = Document(
        title="T",
        author="",
        page_count=1,
        language="de",
        blocks=[
            Block(
                id="b1",
                type="table",
                text=" ",
                page=1,
                cells=[["Einleitung", "4"]],
            ),
            Block(
                id="b2",
                type="list",
                text="",
                page=1,
                list_items=[{"text": "erster Punkt", "level": 0}],
            ),
        ],
    )
    blocks = make_chunks(doc, max_tokens=1000)[0]["blocks"]
    assert blocks[0]["cells"] == [["Einleitung", "4"]]
    assert blocks[1]["list_items"] == [{"text": "erster Punkt", "level": 0}]


def test_doc_map_reference_index() -> None:
    doc_map = build_doc_map(_doc())
    assert "reference_index" in doc_map
    assert doc_map["protected_terms"]


def test_quick_summary_uses_headings_with_first_paragraphs() -> None:
    assert quick_summary(_doc()) == "Kapitel Eins: Der CamelCaseWert und USB2 werden benutzt."
    long_doc = Document(
        title="T",
        author="",
        page_count=1,
        language="de",
        blocks=[
            Block(id="h", type="heading", text="Kapitel", page=1, level=1),
            Block(id="p", type="paragraph", text="x" * 200, page=1),
        ],
    )
    assert quick_summary(long_doc) == "Kapitel: " + "x" * 117 + "…"


def test_verify_flags_missing_protected_term() -> None:
    result = EditorResult(blocks=[SpokenBlock(kind="paragraph", text="ein wert wird benutzt")])
    source = [{"text": "Der CamelCaseWert wird benutzt."}]
    issues = verify_chunk(source, result, ["CamelCaseWert"], "de")
    assert any(i.rule == "protected_term" and i.is_error for i in issues)


def test_verify_flags_leftover_markup() -> None:
    result = EditorResult(blocks=[SpokenBlock(kind="paragraph", text="wert **fett** 1")])
    source = [{"text": "wert **fett** 1"}]
    issues = verify_chunk(source, result, [], "de")
    assert any(i.rule == "markup" for i in issues)


def test_verify_clean_text_has_only_soft_issues() -> None:
    result = EditorResult(
        blocks=[SpokenBlock(kind="paragraph", text="Der Wert beträgt 5 Grad und ist stabil genug.")]
    )
    source = [{"text": "Der Wert beträgt 5 Grad und ist stabil genug."}]
    issues = verify_chunk(source, result, [], "de")
    assert not any(i.is_error for i in issues)


def test_run_script_end_to_end(tmp_path, monkeypatch) -> None:
    """Full S1..S7 with a fake LLM that echoes faithful JSON."""
    import json

    import httpx

    from haldio.config import Config
    from haldio.llm.client import LlmClient
    from haldio.pipeline.run import run_script
    from synthetic import make_test_pdf

    monkeypatch.setattr("haldio.pipeline.run.quick_summary", lambda doc: "KURZGEHALTEN")

    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "blocks": [{"kind": "paragraph", "text": "Gesprochener Text mit Wert 5."}],
            "warnings": [],
            "unresolved_references": [],
        }
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )

    pdf = make_test_pdf(tmp_path / "d.pdf")
    config = Config()

    def factory() -> LlmClient:
        return LlmClient(config.llm, transport=httpx.MockTransport(handler))

    result = run_script(pdf, config, tmp_path / "job", client_factory=factory)
    assert result.return_code == 0
    assert result.chunks >= 1
    doc_map = json.loads(
        (tmp_path / "job" / "02_plan" / "doc_map.json").read_text(encoding="utf-8")
    )
    assert doc_map["summary"] == "KURZGEHALTEN"  # fake answer has no summary key
    assert doc_map["summary_source"] == "fallback"
    script = tmp_path / "job" / "04_script" / "script.md"
    assert script.is_file()
    assert "Gesprochener Text" in script.read_text(encoding="utf-8")
    assert (tmp_path / "job" / "qa_report.html").is_file()


def test_llm_summary_rejects_bad_answers() -> None:
    """Non-JSON and non-object answers go to the fallback (return None)."""

    class _Answer:
        def __init__(self, text: str) -> None:
            self.text = text

    class _Client:
        def __init__(self, text: str) -> None:
            self._text = text

        def chat(self, system: str, user: str, **kwargs) -> _Answer:
            return _Answer(self._text)

    doc = _doc()
    from haldio.pipeline.plan import llm_summary

    assert llm_summary(_Client("not json"), doc) is None
    assert llm_summary(_Client("[1, 2]"), doc) is None
    assert llm_summary(_Client('{"summary": "", "topics": []}'), doc) is None
    assert llm_summary(_Client('{"summary": "Fünf Sätze.", "topics": ["A"]}'), doc) == (
        "Fünf Sätze.",
        ["A"],
    )


def test_run_script_llm_writes_the_plan_summary(tmp_path) -> None:
    """S3: the planner answer becomes the summary and the main topics."""
    import json

    import httpx

    from haldio.config import Config
    from haldio.llm.client import LlmClient
    from haldio.pipeline.run import run_script
    from synthetic import make_test_pdf

    planner = {
        "summary": "Fünf Sätze über das Buch. Satz zwei. Satz drei. Satz vier. Satz fünf.",
        "topics": ["Aufnahme", "Mischung", "Mastering"],
    }
    editor = {
        "blocks": [{"kind": "paragraph", "text": "Gesprochener Text mit Wert 5."}],
        "warnings": [],
        "unresolved_references": [],
    }
    answers = iter([json.dumps(planner)])

    def handler(request: httpx.Request) -> httpx.Response:
        content = next(answers, json.dumps(editor))
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    config = Config()

    def factory() -> LlmClient:
        return LlmClient(config.llm, transport=httpx.MockTransport(handler))

    result = run_script(
        make_test_pdf(tmp_path / "d.pdf"), config, tmp_path / "job", client_factory=factory
    )
    assert result.return_code == 0
    doc_map = json.loads(
        (tmp_path / "job" / "02_plan" / "doc_map.json").read_text(encoding="utf-8")
    )
    assert doc_map["summary_source"] == "llm"
    assert doc_map["summary"].startswith("Fünf Sätze")
    assert doc_map["main_topics"] == ["Aufnahme", "Mischung", "Mastering"]


def test_run_script_summary_falls_back_when_llm_fails(tmp_path, monkeypatch) -> None:
    """A failing planner call keeps quick_summary and stores the source."""
    import json

    import httpx

    from haldio.config import Config
    from haldio.llm.client import LlmClient
    from haldio.pipeline.run import run_script
    from synthetic import make_test_pdf

    monkeypatch.setattr("haldio.pipeline.run.quick_summary", lambda doc: "FALLBACK")
    editor = {
        "blocks": [{"kind": "paragraph", "text": "Gesprochener Text mit Wert 5."}],
        "warnings": [],
        "unresolved_references": [],
    }
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("down", request=request)  # planner call fails
        return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(editor)}}]})

    config = Config()

    def factory() -> LlmClient:
        return LlmClient(config.llm, transport=httpx.MockTransport(handler))

    result = run_script(
        make_test_pdf(tmp_path / "d.pdf"), config, tmp_path / "job", client_factory=factory
    )
    assert result.return_code == 0
    doc_map = json.loads(
        (tmp_path / "job" / "02_plan" / "doc_map.json").read_text(encoding="utf-8")
    )
    assert doc_map["summary_source"] == "fallback"
    assert doc_map["summary"] == "FALLBACK"
    assert calls["n"] >= 2  # the edit stage still ran after the planner failure


def test_parse_rejects_answer_without_blocks_key() -> None:
    from haldio.pipeline.edit import parse_editor_result

    with pytest.raises(ValueError, match="blocks"):
        parse_editor_result('{"script": "Kapitel Eins. Der Text."}')


def test_examples_are_added_to_system_prompt() -> None:
    from haldio.pipeline.edit import system_with_examples

    system = system_with_examples("BASE", [{"name": "table", "source": "IN", "output": "OUT"}])
    assert system.startswith("BASE")
    assert "## table" in system and "IN" in system and "OUT" in system


def test_wrong_shape_answer_is_retried() -> None:
    """A {"script": ...} answer must be retried, not accepted as empty."""
    import json

    import httpx

    from haldio.config import Config
    from haldio.llm.client import LlmClient
    from haldio.pipeline.edit import parse_editor_result  # noqa: F401 - import smoke
    from haldio.pipeline.run import edit_chunk_with_retry

    chunk = make_chunks(_doc(), max_tokens=1000)[0]
    answers = iter(
        [
            '{"script": "etwas Text"}',
            json.dumps(
                {
                    "blocks": [{"kind": "paragraph", "text": "Der CamelCaseWert und USB2."}],
                    "warnings": [],
                    "unresolved_references": [],
                }
            ),
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"choices": [{"message": {"content": next(answers)}}]})

    config = Config()
    client = LlmClient(config.llm, transport=httpx.MockTransport(handler))
    edit, _issues = edit_chunk_with_retry(chunk, client, "SYS", "de", 2)
    assert edit.attempts == 2
    assert not edit.needs_review
    assert edit.result is not None and edit.result.blocks
