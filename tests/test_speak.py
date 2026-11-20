"""Tests for TTS unit splitting, normalization and the S8/S9 stages."""

from __future__ import annotations

import shutil

import pytest

from haldio.pipeline.speak import split_units, synthesize_script, unit_cache_key
from haldio.tts.mock import MockTTSBackend
from haldio.tts.normalizer import load_pronunciations, make_speakable

HAS_FFMPEG = shutil.which("ffmpeg") is not None


def test_split_units_keeps_sentences_apart() -> None:
    text = "Erster Satz. Zweiter Satz. Dritter Satz."
    assert split_units(text, 20) == ["Erster Satz.", "Zweiter Satz.", "Dritter Satz."]


def test_split_units_breaks_long_sentence_at_comma() -> None:
    text = "Ein sehr langer Satz mit Komma, der ueber das Limit hinausgeht."
    units = split_units(text, 40)
    assert all(len(u) <= 40 for u in units)
    assert len(units) > 1


def test_letterless_units_merge_into_previous() -> None:
    from haldio.pipeline.speak import _merge_letterless_units

    assert _merge_letterless_units(["Erster Satz.", "—", "•", "Zweiter Satz."]) == [
        "Erster Satz. — •",
        "Zweiter Satz.",
    ]
    assert _merge_letterless_units(["—", "Nur ein Satz."]) == ["Nur ein Satz."]


def test_normalizer_expands_decimals_and_numbers() -> None:
    out = make_speakable("Der Wert betraegt 3,3 Volt und 42 Stueck.", "de")
    assert "drei Komma drei" in out
    assert "zweiundvierzig" in out


def test_normalizer_splits_camel_case() -> None:
    assert "Qt Framework" in make_speakable("QtFramework lädt.", "de")


def test_pronunciations_file_applied(tmp_path) -> None:
    path = tmp_path / "pronunciations.yaml"
    path.write_text("PDF: P D F\n", encoding="utf-8")
    table = load_pronunciations(path)
    assert make_speakable("ein PDF Dokument", "de", table) == "ein P D F Dokument"
    assert load_pronunciations(tmp_path / "missing.yaml") == {}


def _script_data() -> dict:
    return {
        "chunks": [
            {
                "chunk_id": "c0001",
                "blocks": [
                    {"kind": "heading", "level": 1, "text": "Kapitel Eins"},
                    {"kind": "paragraph", "text": "Erster Satz. Zweiter Satz."},
                ],
                "warnings": [],
                "needs_review": False,
            }
        ]
    }


def test_synthesize_script_writes_units_and_caches(tmp_path) -> None:
    from haldio.config import TtsConfig

    result = synthesize_script(
        _script_data(), MockTTSBackend(), "mock", TtsConfig(), tmp_path, "de"
    )
    assert result.ok
    assert result.synthesized == 3
    assert (tmp_path / "05_speak" / "units.json").is_file()
    again = synthesize_script(_script_data(), MockTTSBackend(), "mock", TtsConfig(), tmp_path, "de")
    assert again.cached == 3 and again.synthesized == 0


def test_unit_cache_key_changes_with_voice() -> None:
    assert unit_cache_key("text", "a", "mock") != unit_cache_key("text", "b", "mock")


def test_unit_cache_key_changes_with_backend_and_model() -> None:
    assert unit_cache_key("text", "a", "qwencpp") != unit_cache_key("text", "a", "qwen_local")
    assert unit_cache_key("text", "a", "qwencpp", "m-Q8_0.gguf") != unit_cache_key(
        "text", "a", "qwencpp", "m-Q4_K.gguf"
    )


def test_master_needs_units_file(tmp_path) -> None:
    from haldio.pipeline.master import make_master

    result = make_master(tmp_path, ["mp3"], {"paragraph": 500})
    if not HAS_FFMPEG:
        assert result.error == "ffmpeg not found - please install ffmpeg"
    else:
        assert result.error == "missing 05_speak/units.json - run stage S8 first"


@pytest.mark.skipif(not HAS_FFMPEG, reason="ffmpeg not installed")
def test_master_merges_units(tmp_path) -> None:
    from haldio.config import TtsConfig

    synthesize_script(_script_data(), MockTTSBackend(), "mock", TtsConfig(), tmp_path, "de")
    from haldio.pipeline.master import make_master

    result = make_master(tmp_path, ["mp3"], {"paragraph": 100, "heading": 200, "chapter": 300})
    assert result.ok
    assert (tmp_path / "06_master" / "book.mp3").stat().st_size > 0


def test_run_book_end_to_end(tmp_path) -> None:
    """S1..S9 with a fake LLM and MockTTS; master only runs when ffmpeg exists."""
    import json

    import httpx

    from haldio.config import Config
    from haldio.llm.client import LlmClient
    from haldio.pipeline.run import run_book
    from synthetic import make_test_pdf

    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "blocks": [{"kind": "paragraph", "text": "Gesprochener Text. Noch ein Satz."}],
            "warnings": [],
            "unresolved_references": [],
        }
        return httpx.Response(
            200, json={"choices": [{"message": {"content": json.dumps(payload)}}]}
        )

    config = Config()

    def factory() -> LlmClient:
        return LlmClient(config.llm, transport=httpx.MockTransport(handler))

    result = run_book(
        make_test_pdf(tmp_path / "d.pdf"), config, tmp_path / "job", client_factory=factory
    )
    assert result.script.ok and result.script.chunks >= 1
    assert result.speak.ok
    if HAS_FFMPEG:
        assert result.master.ok
        assert result.return_code == 0
    else:
        assert "ffmpeg" in result.master.error
