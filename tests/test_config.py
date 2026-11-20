"""Tests for configuration loading."""

from __future__ import annotations

from pathlib import Path

from haldio.config import Config, load_config


def test_defaults_match_the_brief() -> None:
    cfg = Config()
    assert cfg.llm.base_url == "http://127.0.0.1:8080/v1"
    assert cfg.tts.backend == "mock"
    assert cfg.server.port == 8505
    assert cfg.audio.formats == ["mp3", "ogg"]
    assert cfg.audio.pause_ms.chapter == 1500


def test_missing_file_keeps_defaults(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "absent.yaml")
    assert cfg.editor.max_retries == 2


def test_partial_yaml_overrides_only_given_keys(tmp_path: Path) -> None:
    path = tmp_path / "config.yaml"
    path.write_text("server:\n  port: 9000\ntts:\n  backend: qwen_local\n", encoding="utf-8")
    cfg = load_config(path)
    assert cfg.server.port == 9000
    assert cfg.tts.backend == "qwen_local"
    assert cfg.server.host == "127.0.0.1"
