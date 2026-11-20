"""LM Studio client (OpenAI compatible) for the editor LLM."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

import httpx

from haldio.config import LlmConfig

_THINK = re.compile(r"<think.*?</think\s*>", re.DOTALL)


class LlmError(RuntimeError):
    """Raised when the LLM cannot be reached or answers with an error."""


def llm_reachable(llm: LlmConfig, timeout: float = 3.0) -> bool:
    """True when LM Studio answers the model list endpoint."""
    try:
        response = httpx.get(
            f"{llm.base_url}/models",
            headers={"Authorization": f"Bearer {llm.api_key}"},
            timeout=timeout,
        )
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def loaded_llm_models(timeout: float = 15.0) -> list[str] | None:
    """Model ids LM Studio keeps in memory.

    Uses the verified `lms ps --json` command (the REST path /api/v0/models
    answered 404 on this machine). Returns None when no check is possible -
    callers then fall back to the manual gate.
    """
    import subprocess

    try:
        done = subprocess.run(  # noqa: S603 - fixed command, no shell
            ["lms", "ps", "--json"],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if done.returncode == 0:
            entries = json.loads(done.stdout)
            return [str(e.get("modelIdentifier") or e.get("id") or e) for e in entries]
    except (OSError, ValueError, subprocess.TimeoutExpired):
        pass
    return None


@dataclass
class ChatResult:
    """One assistant answer, already cleaned."""

    text: str
    raw: dict[str, Any] = field(default_factory=dict)

    def json_data(self) -> dict[str, Any]:
        """Parse the answer as one JSON object."""
        return parse_json_object(strip_thinking(self.text))


def strip_thinking(text: str) -> str:
    """Remove <|im_start|>-style reasoning blocks before parsing."""
    cleaned = _THINK.sub("", text)
    cleaned = re.sub(r"</?think>", "", cleaned)
    return cleaned.strip()


def parse_json_object(text: str) -> dict[str, Any]:
    """Parse a JSON object from text, tolerating prose around it."""
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise LlmError("answer is not JSON") from None
        try:
            data = json.loads(text[start : end + 1])
        except json.JSONDecodeError as error:
            raise LlmError(f"invalid JSON answer: {error}") from error
    if not isinstance(data, dict):
        raise LlmError("JSON answer is not an object")
    return data


class LlmClient:
    """Small client for the /v1/chat/completions endpoint."""

    def __init__(self, config: LlmConfig, transport: httpx.BaseTransport | None = None) -> None:
        self.config = config
        self._client = httpx.Client(
            base_url=config.base_url.rstrip("/"),
            headers={"Authorization": f"Bearer {config.api_key}"},
            timeout=config.timeout_s,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> LlmClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def list_models(self) -> list[str]:
        """Model ids served by the endpoint."""
        try:
            response = self._client.get("/models")
            response.raise_for_status()
        except httpx.HTTPError as error:
            raise LlmError(f"cannot list models: {error}") from error
        payload = response.json()
        return [str(item["id"]) for item in payload.get("data", []) if "id" in item]

    def chat(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any] | None = None,
        temperature: float | None = None,
    ) -> ChatResult:
        """Send one system+user pair. `json_schema` requests a structured answer."""
        body: dict[str, Any] = {
            "model": self.config.model,
            "temperature": self.config.temperature if temperature is None else temperature,
            "max_tokens": self.config.max_output_tokens,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if json_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "editor_output", "schema": json_schema, "strict": True},
            }
        try:
            response = self._client.post("/chat/completions", json=body)
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            detail = error.response.text[:200]
            if json_schema is not None and _schema_not_supported(detail):
                body.pop("response_format")
                response = self._client.post("/chat/completions", json=body)
                response.raise_for_status()
            else:
                raise LlmError(f"LLM call failed: {error} {detail}") from error
        except httpx.HTTPError as error:
            raise LlmError(f"LLM call failed: {error}") from error
        data = response.json()
        try:
            text = data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError, TypeError) as error:
            raise LlmError("unexpected LLM answer shape") from error
        return ChatResult(text=text, raw=data)


def _schema_not_supported(detail: str) -> bool:
    lower = detail.lower()
    return "response_format" in lower or "json_schema" in lower
