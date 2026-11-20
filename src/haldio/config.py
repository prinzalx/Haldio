"""Configuration loading: config.yaml for settings, .env for secrets."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field


class LlmConfig(BaseModel):
    """Editor LLM served by LM Studio (OpenAI compatible)."""

    base_url: str = "http://127.0.0.1:8080/v1"
    api_key: str = "lm-studio"
    model: str = "bubo"
    temperature: float = 0.2
    max_input_tokens: int = 1500
    max_output_tokens: int = 4000
    timeout_s: int = 600
    strip_thinking: bool = True


class TtsConfig(BaseModel):
    """Local Qwen3-TTS backend (worker subprocess) or mock."""

    backend: Literal["mock", "qwen_local"] = "mock"
    mode: Literal["clone", "custom_voice"] = "clone"
    model_id: str = "Qwen/Qwen3-TTS-12Hz-1.7B-Base"
    model_path: str = ""
    worker_python: str = ""
    device: str = "auto"
    dtype: str = "bfloat16"
    language: str = "auto"
    speaker: str = ""
    instruct: str = ""
    reference_audio: str = ""
    reference_text: str = ""
    max_chars_per_unit: int = 400
    batch_size: int = 1
    confirm_before_start: bool = True


class EditorConfig(BaseModel):
    """Editor stage settings (prompt, verification, retries)."""

    prompt_version: str = "v1"
    fidelity_check: bool = True
    max_retries: int = 2
    review_before_tts: bool = False


class PauseConfig(BaseModel):
    """Pause lengths between audio units, in milliseconds."""

    paragraph: int = 500
    heading: int = 900
    chapter: int = 1500


class AudioConfig(BaseModel):
    """Audio output settings."""

    formats: list[str] = Field(default_factory=lambda: ["mp3", "ogg"])
    mp3_bitrate_kbps: int = 96
    channels: int = 1
    target_lufs: int = -18
    pause_ms: PauseConfig = Field(default_factory=PauseConfig)


class PathsConfig(BaseModel):
    """File system locations."""

    data_dir: Path = Path("./data")


class HooksConfig(BaseModel):
    """Optional shell commands around the LLM and TTS stages (model unload)."""

    before_edit: str = ""
    after_edit: str = ""
    before_speak: str = ""
    after_speak: str = ""


class ServerConfig(BaseModel):
    """Web server settings."""

    host: str = "127.0.0.1"
    port: int = 8505
    max_upload_mb: int = 100


class Config(BaseModel):
    """Root configuration object."""

    llm: LlmConfig = Field(default_factory=LlmConfig)
    tts: TtsConfig = Field(default_factory=TtsConfig)
    editor: EditorConfig = Field(default_factory=EditorConfig)
    policies: dict[str, object] = Field(default_factory=dict)
    audio: AudioConfig = Field(default_factory=AudioConfig)
    paths: PathsConfig = Field(default_factory=PathsConfig)
    hooks: HooksConfig = Field(default_factory=HooksConfig)
    server: ServerConfig = Field(default_factory=ServerConfig)


def load_config(path: Path | None = None) -> Config:
    """Load config.yaml if present; missing keys keep their defaults."""
    if path is None:
        path = Path("config.yaml")
    if not path.is_file():
        return Config()
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return Config.model_validate(raw)
