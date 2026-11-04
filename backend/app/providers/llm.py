"""Chat LLM providers."""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any, Protocol

import httpx

from app.config import Settings

log = logging.getLogger(__name__)


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


class ThinkFilter:
    """Drops inline <think>...</think> reasoning blocks from a token stream, including tags that
    arrive split across chunks. Call ``flush()`` at the end of the stream."""

    OPEN, CLOSE = "<think>", "</think>"

    def __init__(self) -> None:
        self.inside = False
        self.buf = ""

    @staticmethod
    def _partial(text: str, tag: str) -> int:
        """Length of the longest suffix of text that is a proper prefix of tag."""
        for n in range(min(len(tag) - 1, len(text)), 0, -1):
            if text.endswith(tag[:n]):
                return n
        return 0

    def __call__(self, piece: str) -> str:
        text, self.buf, out = self.buf + piece, "", ""
        while text:
            tag = self.CLOSE if self.inside else self.OPEN
            i = text.find(tag)
            if i >= 0:
                if not self.inside:
                    out += text[:i]
                text, self.inside = text[i + len(tag):], not self.inside
                continue
            keep = self._partial(text, tag)
            if not self.inside:
                out += text[: len(text) - keep]
            self.buf = text[len(text) - keep:] if keep else ""
            break
        return out

    def flush(self) -> str:
        rest, self.buf = ("" if self.inside else self.buf), ""
        return rest


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
            think = ThinkFilter()
            async for line in r.aiter_lines():
                if not line:
                    continue
                data = json.loads(line)
                if data.get("error"):
                    raise RuntimeError(data["error"])
                piece = think(data.get("message", {}).get("content", ""))
                if piece:
                    yield piece
                if data.get("done"):
                    break
            if tail := think.flush():
                yield tail

    async def complete(self, messages: list[dict], *, model: str | None = None, **extra) -> str:
        r = await self._client.post("/api/chat", json=self._payload(messages, model, False, think=False, **extra))
        if r.status_code == 400 and "think" in r.text:  # model doesn't support the think flag
            r = await self._client.post("/api/chat", json=self._payload(messages, model, False, **extra))
        r.raise_for_status()
        return _THINK_RE.sub("", r.json()["message"]["content"]).strip()

    async def complete_json(self, messages: list[dict], *, model: str | None = None) -> Any:
        return parse_json_loose(await self.complete(messages, model=model, format="json"))

    async def list_models(self) -> list[str]:
        r = await self._client.get("/api/tags", timeout=5)
        r.raise_for_status()
        return [m["name"] for m in r.json().get("models", [])]


PROVIDER_LABEL = {"groq": "Groq", "gemini": "Gemini", "openai_compatible": "LLM provider", "ollama": "Ollama"}
KEY_HINT = {"groq": "GROQ_API_KEY (free key: https://console.groq.com/keys)",
            "gemini": "GEMINI_API_KEY (free key: https://aistudio.google.com/apikey)",
            "openai_compatible": "RAG_LLM_API_KEY"}


class LLMError(RuntimeError):
    """Provider error with a message that is safe and useful to show in the UI."""


class OpenAICompatLLM:
    """Any OpenAI-compatible Chat Completions API: Groq, Gemini, OpenRouter, Mistral, NVIDIA NIM, vLLM...

    Retries rate limits (429) and transient 5xx with backoff (honouring Retry-After), falls back
    from JSON mode when a model or provider rejects it, and turns HTTP errors into actionable messages.
    """

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.s = settings
        self.label = PROVIDER_LABEL.get(settings.llm_provider, "LLM provider")
        headers = {"Authorization": f"Bearer {settings.api_key}"} if settings.api_key else {}
        self._client = client or httpx.AsyncClient(base_url=settings.llm_base_url + "/", timeout=settings.request_timeout, headers=headers)

    # ------------------------------------------------------------------ request plumbing

    def _body(self, messages: list[dict], model: str | None, *, stream: bool, json_mode: bool = False) -> dict:
        body: dict[str, Any] = {
            "model": model or self.s.chat_model, "messages": messages, "stream": stream,
            "temperature": self.s.temperature, "max_tokens": self.s.max_output_tokens,
        }
        if self.s.reasoning_effort:
            body["reasoning_effort"] = self.s.reasoning_effort
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        return body

    @staticmethod
    def _retry_after(r: httpx.Response, attempt: int) -> float:
        for h in ("retry-after", "x-ratelimit-reset-requests", "x-ratelimit-reset-tokens"):
            v = r.headers.get(h)
            if not v:
                continue
            m = re.fullmatch(r"(?:(\d+)m)?(\d+(?:\.\d+)?)(ms|s)?", v.strip())
            if m:
                secs = float(m.group(2)) / (1000 if m.group(3) == "ms" else 1) + 60 * int(m.group(1) or 0)
                return min(max(secs, 0.5), 30.0)
        return min(2.0 ** attempt, 30.0)

    def _error(self, r: httpx.Response, model: str) -> LLMError:
        try:
            detail = r.json()
            detail = detail[0] if isinstance(detail, list) and detail else detail
            msg = (detail.get("error") or {}).get("message") if isinstance(detail.get("error"), dict) else detail.get("error")
            msg = msg or detail.get("message") or r.text
        except Exception:
            msg = r.text
        msg = str(msg)[:300]
        if r.status_code in (401, 403):
            return LLMError(f"{self.label} rejected the API key ({r.status_code}). Set {KEY_HINT.get(self.s.llm_provider, 'the API key')} in .env. {msg}")
        if r.status_code == 404:
            return LLMError(f"{self.label}: model '{model}' not found. Check available models at /api/health and set RAG_CHAT_MODEL / RAG_PLANNER_MODEL. {msg}")
        if r.status_code == 429:
            return LLMError(f"{self.label} rate limit reached (free tier). Wait a minute, switch to Fast mode, or use another model. {msg}")
        return LLMError(f"{self.label} error {r.status_code}: {msg}")

    async def _send(self, body: dict, *, stream: bool) -> httpx.Response:
        """POST /chat/completions with retries. For stream=True the caller must close the response."""
        for attempt in range(self.s.max_retries + 1):
            req = self._client.build_request("POST", "chat/completions", json=body)
            r = await self._client.send(req, stream=stream)
            if r.status_code < 400:
                return r
            if stream:
                await r.aread()
                await r.aclose()
            retryable = r.status_code == 429 or r.status_code >= 500
            if retryable and attempt < self.s.max_retries:
                wait = self._retry_after(r, attempt)
                log.warning("%s returned %s; retrying in %.1fs (attempt %d)", self.label, r.status_code, wait, attempt + 1)
                await asyncio.sleep(wait)
                continue
            if r.status_code == 400 and "response_format" in body:
                # JSON mode unsupported for this model, or the model's JSON failed validation: retry in plain mode.
                log.info("%s rejected JSON mode (%s); retrying without it", self.label, r.text[:160])
                body = {k: v for k, v in body.items() if k != "response_format"}
                continue
            raise self._error(r, body["model"])
        raise self._error(r, body["model"])

    # ------------------------------------------------------------------ LLM interface

    async def stream(self, messages: list[dict], *, model: str | None = None) -> AsyncIterator[str]:
        r = await self._send(self._body(messages, model, stream=True), stream=True)
        think = ThinkFilter()
        try:
            async for line in r.aiter_lines():
                if not line.startswith("data:"):
                    continue
                payload = line[5:].strip()
                if payload == "[DONE]":
                    break
                data = json.loads(payload)
                if data.get("error"):
                    raise LLMError(f"{self.label}: {data['error'].get('message', data['error']) if isinstance(data['error'], dict) else data['error']}")
                for choice in data.get("choices") or []:
                    piece = think((choice.get("delta") or {}).get("content") or "")
                    if piece:
                        yield piece
            if tail := think.flush():
                yield tail
        finally:
            await r.aclose()

    async def complete(self, messages: list[dict], *, model: str | None = None, json_mode: bool = False) -> str:
        r = await self._send(self._body(messages, model, stream=False, json_mode=json_mode), stream=False)
        choices = r.json().get("choices") or []
        content = (choices[0].get("message") or {}).get("content") if choices else ""
        return _THINK_RE.sub("", content or "").strip()

    async def complete_json(self, messages: list[dict], *, model: str | None = None) -> Any:
        text = await self.complete(messages, model=model, json_mode=True)
        try:
            return parse_json_loose(text)
        except (json.JSONDecodeError, ValueError):
            # One corrective retry: models occasionally wrap or truncate JSON.
            fix = messages + [{"role": "assistant", "content": text[:4000]},
                              {"role": "user", "content": "That was not valid JSON. Reply with only the corrected JSON object."}]
            return parse_json_loose(await self.complete(fix, model=model, json_mode=True))

    async def list_models(self) -> list[str]:
        r = await self._client.get("models", timeout=8)
        if r.status_code >= 400:
            raise self._error(r, "")
        return sorted(m["id"].removeprefix("models/") for m in r.json().get("data", []))


def build_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "ollama":
        return OllamaLLM(settings)
    if not settings.llm_base_url:
        raise ValueError("RAG_LLM_BASE_URL is required for llm_provider=openai_compatible")
    if not settings.chat_model:
        raise ValueError("RAG_CHAT_MODEL is required for llm_provider=openai_compatible")
    if not settings.api_key:
        log.warning("No API key configured for %s; set %s", settings.llm_provider, KEY_HINT.get(settings.llm_provider, "the key"))
    return OpenAICompatLLM(settings)
