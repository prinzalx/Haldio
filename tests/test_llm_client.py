"""Tests for the LLM client using a mock HTTP transport."""

from __future__ import annotations

import json

import httpx
import pytest

from haldio.config import LlmConfig
from haldio.llm.client import LlmClient, LlmError, parse_json_object, strip_thinking


def test_strip_thinking_removes_reasoning() -> None:
    text = "<think>internal reasoning</think>RESULT"
    assert strip_thinking(text) == "RESULT"
    assert strip_thinking("ok") == "ok"


def test_parse_json_object_with_prose() -> None:
    assert parse_json_object('noise {"a": 1} noise') == {"a": 1}


def test_parse_json_object_rejects_non_object() -> None:
    with pytest.raises(LlmError):
        parse_json_object("[1, 2]")


def _client(handler) -> LlmClient:
    return LlmClient(LlmConfig(model="bubo"), transport=httpx.MockTransport(handler))


def test_chat_returns_content() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "bubo"
        return httpx.Response(200, json={"choices": [{"message": {"content": "hallo"}}]})

    with _client(handler) as client:
        assert client.chat("s", "u").text == "hallo"


def test_chat_falls_back_when_schema_rejected() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        body = json.loads(request.content)
        if "response_format" in body:
            return httpx.Response(400, text="response_format json_schema not supported")
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    with _client(handler) as client:
        assert client.chat("s", "u", json_schema={"type": "object"}).text == "{}"
    assert calls["n"] == 2


def test_list_models() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"id": "bubo"}, {"id": "other"}]})

    with _client(handler) as client:
        assert client.list_models() == ["bubo", "other"]
