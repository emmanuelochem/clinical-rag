"""Chat LLM providers."""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx

from app.config import Settings


class LLM(Protocol):
    def stream(self, messages: list[dict], *, model: str | None = None) -> AsyncIterator[str]: ...
    async def complete(self, messages: list[dict], *, model: str | None = None) -> str: ...
    async def complete_json(self, messages: list[dict], *, model: str | None = None) -> Any: ...


_THINK_RE = re.compile(r"<think>.*?</think>", re.S)


def parse_json_loose(text: str) -> Any:
    """Parse JSON from model output, tolerating code fences, reasoning tags and trailing prose."""
    text = _THINK_RE.sub("", text).strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"(\{.*\}|\[.*\])", text, re.S)
        if m:
            return json.loads(m.group(1))
        raise


class OllamaLLM:
    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.s = settings
        self._client = client or httpx.AsyncClient(base_url=settings.ollama_url, timeout=settings.request_timeout)

    def _payload(self, messages: list[dict], model: str | None, stream: bool, **extra) -> dict:
        return {
            "model": model or self.s.chat_model,
            "messages": messages,
            "stream": stream,
            "options": {"temperature": self.s.temperature, "num_ctx": self.s.num_ctx},
            **extra,
        }

    async def stream(self, messages: list[dict], *, model: str | None = None) -> AsyncIterator[str]:
        async with self._client.stream("POST", "/api/chat", json=self._payload(messages, model, True)) as r:
            if r.status_code == 404:
                raise RuntimeError(f"Model '{model or self.s.chat_model}' not found in Ollama. Run: ollama pull <model>")
            r.raise_for_status()
            in_think = False
            async for line in r.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if data.get("error"):
                    raise RuntimeError(data["error"])
                piece = data.get("message", {}).get("content", "")
                # Hide inline reasoning blocks emitted by some local "thinking" models.
                if "<think>" in piece:
                    in_think = True
                if in_think:
                    if "</think>" in piece:
                        in_think = False
                        piece = piece.split("</think>", 1)[1]
                    else:
                        continue
                if piece:
                    yield piece
                if data.get("done"):
                    break

    async def complete(self, messages: list[dict], *, model: str | None = None, **extra) -> str:
        r = await self._client.post("/api/chat", json=self._payload(messages, model, False, think=False, **extra))
        if r.status_code == 400 and "think" in r.text:  # model doesn't support the think flag
            r = await self._client.post("/api/chat", json=self._payload(messages, model, False, **extra))
        r.raise_for_status()
        return _THINK_RE.sub("", r.json()["message"]["content"]).strip()

    async def complete_json(self, messages: list[dict], *, model: str | None = None) -> Any:
        return parse_json_loose(await self.complete(messages, model=model, format="json"))
