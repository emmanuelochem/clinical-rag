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
    """Local cross-encoder (e.g. BAAI/bge-reranker-base) via sentence-transformers.

    Model weights download once from Hugging Face and then run fully offline on CPU/GPU.
    """

    name = "cross-encoder"

    def __init__(self, model_name: str):
        from sentence_transformers import CrossEncoder  # optional dependency

        self._model = CrossEncoder(model_name, max_length=512)

    async def score(self, query: str, passages: list[str]) -> list[float]:
        if not passages:
            return []
        pairs = [(query, p) for p in passages]
        raw = await asyncio.to_thread(self._model.predict, pairs, batch_size=16, show_progress_bar=False)
        return [1 / (1 + math.exp(-float(x))) if not 0 <= float(x) <= 1 else float(x) for x in raw]


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
            return CrossEncoderReranker(settings.cross_encoder_model)
        except ImportError:
            log.warning(
                "sentence-transformers not installed; falling back to LLM reranking. "
                "Install with: pip install '.[rerank]'"
            )
            return LLMReranker(llm, settings.planner)
        except Exception as e:
            log.warning("Could not load cross-encoder %s (%s); falling back to LLM reranking.", settings.cross_encoder_model, e)
            return LLMReranker(llm, settings.planner)
    if settings.reranker == "llm":
        return LLMReranker(llm, settings.planner)
    return NoopReranker()
