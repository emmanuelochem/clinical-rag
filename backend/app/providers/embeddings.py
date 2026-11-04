"""Embedding providers."""

from __future__ import annotations

from typing import Protocol

import asyncio
import logging

import httpx

from app.config import Settings

log = logging.getLogger(__name__)


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


class LocalEmbedder:
    """In-process embeddings with fastembed (ONNX Runtime, CPU; no PyTorch, no server, no API key).

    The model (BAAI/bge-small-en-v1.5 by default, ~70 MB) downloads from Hugging Face on first use
    and is cached under ``<data_dir>/models``.
    """

    def __init__(self, settings: Settings, model=None):
        self.s = settings
        self._model = model
        self._lock = asyncio.Lock()

    async def _get(self):
        if self._model is None:
            async with self._lock:
                if self._model is None:
                    from fastembed import TextEmbedding

                    log.info("Loading local embedding model %s (first run downloads it)", self.s.embed_model)
                    try:
                        self._model = await asyncio.to_thread(
                            TextEmbedding, self.s.embed_model, cache_dir=str(self.s.models_dir))
                    except Exception as e:
                        raise RuntimeError(
                            f"Could not load the local embedding model '{self.s.embed_model}'. The first run downloads it "
                            f"from huggingface.co (needs internet access); it is then cached in {self.s.models_dir}. ({e})"
                        ) from e
        return self._model

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        model = await self._get()
        vecs = await asyncio.to_thread(lambda: list(model.embed(texts, batch_size=self.s.embed_batch_size)))
        return [v.tolist() for v in vecs]

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return await self._embed([self.s.embed_doc_prefix + t for t in texts])

    async def embed_query(self, text: str) -> list[float]:
        return (await self._embed([self.s.embed_query_prefix + text]))[0]

    async def dimension(self) -> int:
        return len(await self.embed_query("dimension probe"))


def build_embedder(settings: Settings) -> Embedder:
    return OllamaEmbedder(settings) if settings.embed_provider == "ollama" else LocalEmbedder(settings)
