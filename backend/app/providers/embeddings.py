"""Embedding providers."""

from __future__ import annotations

from typing import Protocol

import httpx

from app.config import Settings


class Embedder(Protocol):
    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...
    async def embed_query(self, text: str) -> list[float]: ...
    async def dimension(self) -> int: ...


class OllamaEmbedder:
    """Embeddings via Ollama's ``/api/embed`` endpoint (batched)."""

    def __init__(self, settings: Settings, client: httpx.AsyncClient | None = None):
        self.s = settings
        self._client = client or httpx.AsyncClient(base_url=settings.ollama_url, timeout=settings.request_timeout)
        self._dim: int | None = None

    async def _embed(self, inputs: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(inputs), self.s.embed_batch_size):
            batch = inputs[i : i + self.s.embed_batch_size]
            r = await self._client.post("/api/embed", json={"model": self.s.embed_model, "input": batch, "truncate": True})
            if r.status_code == 404:
                raise RuntimeError(
                    f"Embedding model '{self.s.embed_model}' not found in Ollama. Run: ollama pull {self.s.embed_model}"
                )
            r.raise_for_status()
            out.extend(r.json()["embeddings"])
        return out

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed([self.s.embed_doc_prefix + t for t in texts])

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([self.s.embed_query_prefix + text]))[0]

    async def dimension(self) -> int:
        if self._dim is None:
            self._dim = len(await self.embed_query("dimension probe"))
        return self._dim
