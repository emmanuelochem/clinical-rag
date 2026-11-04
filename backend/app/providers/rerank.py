"""Rerankers: score (query, passage) pairs more precisely than first-stage retrieval."""

from __future__ import annotations

import asyncio
import logging
import math
from typing import Protocol

from app.config import Settings
from app.providers.llm import LLM

log = logging.getLogger(__name__)


class Reranker(Protocol):
    name: str

    async def score(self, query: str, passages: list[str]) -> list[float]: ...


class NoopReranker:
    name = "none"

    async def score(self, query: str, passages: list[str]) -> list[float]:
        # Preserve incoming order: descending pseudo-scores.
        n = len(passages)
        return [float(n - i) / max(n, 1) for i in range(n)]


class CrossEncoderReranker:
    """Local cross-encoder via fastembed (ONNX, CPU). Default ``Xenova/ms-marco-MiniLM-L-6-v2`` (~80 MB);
    ``BAAI/bge-reranker-base`` is more accurate but ~1 GB. Weights download once, then run offline.
    Loads lazily so startup stays fast and a download failure degrades to fused ranking."""

    name = "cross-encoder"

    def __init__(self, model_name: str, cache_dir: str | None = None):
        import fastembed  # noqa: F401  (fail fast at build time if not installed)

        self.model_name, self.cache_dir = model_name, cache_dir
        self._model = None
        self._failed = False
        self._lock = asyncio.Lock()

    async def _get(self):
        if self._model is None and not self._failed:
            async with self._lock:
                if self._model is None and not self._failed:
                    from fastembed.rerank.cross_encoder import TextCrossEncoder

                    try:
                        self._model = await asyncio.to_thread(TextCrossEncoder, self.model_name, cache_dir=self.cache_dir)
                    except Exception as e:
                        log.warning("Could not load reranker %s (%s); using fused ranking", self.model_name, e)
                        self._failed = True
        return self._model

    async def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        model = await self._get()
        if model is None:
            return await NoopReranker().score(query, passages)
        raw = await asyncio.to_thread(lambda: list(model.rerank(query, passages, batch_size=16)))
        return [1 / (1 + math.exp(-float(x))) for x in raw]  # logits -> 0..1


class LLMReranker:
    """Listwise reranking with the local chat model: one prompt grades all candidates 0-10."""

    name = "llm"

    def __init__(self, llm: LLM, model: str):
        self.llm, self.model = llm, model

    async def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        listing = "\n\n".join(f"[{i}] {p[:700]}" for i, p in enumerate(passages))
        prompt = (
            "Rate how useful each passage is for answering the query, from 0 (irrelevant) to 10 "
            "(directly answers it). Respond with JSON: {\"scores\": {\"<index>\": <score>, ...}} "
            "covering every index.\n\n"
            f"Query: {query}\n\nPassages:\n{listing}"
        )
        try:
            data = await self.llm.complete_json([{"role": "user", "content": prompt}], model=self.model)
            scores = data.get("scores", data) if isinstance(data, dict) else {}
            return [float(scores.get(str(i), scores.get(i, 0))) / 10 for i in range(len(passages))]
        except Exception as e:  # never let reranking break retrieval
            log.warning("LLM rerank failed, keeping fused order: %s", e)
            return await NoopReranker().score(query, passages)


def build_reranker(settings: Settings, llm: LLM) -> Reranker:
    if settings.reranker == "cross-encoder":
        try:
            return CrossEncoderReranker(settings.cross_encoder_model, str(settings.models_dir))
        except ImportError:
            log.warning("fastembed not installed; reranking disabled. Install with: pip install fastembed")
            return NoopReranker()
    if settings.reranker == "llm":
        return LLMReranker(llm, settings.planner)
    return NoopReranker()
