"""Hybrid retrieval pipeline.

  query(ies) ──► dense vector search ─┐
             └─► BM25 keyword search ─┴─► Reciprocal Rank Fusion ─► cross-encoder rerank
                                          ─► MMR diversification ─► neighbour expansion
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field

from app.config import Settings
from app.models import RetrievedChunk
from app.providers.embeddings import Embedder
from app.providers.rerank import Reranker
from app.store.vectors import VectorStore, row_to_chunk


@dataclass
class _Cand:
    row: dict
    rrf: float = 0.0
    vector_rank: int | None = None
    keyword_rank: int | None = None
    queries: set[str] = field(default_factory=set)


def _tokens(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2}


def _jaccard(a: set[str], b: set[str]) -> float:
    return len(a & b) / len(a | b) if a and b else 0.0


class HybridRetriever:
    def __init__(self, settings: Settings, store: VectorStore, embedder: Embedder, reranker: Reranker):
        self.s, self.store, self.embedder, self.reranker = settings, store, embedder, reranker

    async def _candidates(self, queries: list[str], where: str | None) -> dict[str, _Cand]:
        vecs = await asyncio.gather(*(self.embedder.embed_query(q) for q in queries))
        cands: dict[str, _Cand] = {}
        for q, vec in zip(queries, vecs, strict=True):
            vres, kres = await asyncio.gather(
                asyncio.to_thread(self.store.vector_search, vec, self.s.vector_candidates, where),
                asyncio.to_thread(self.store.keyword_search, q, self.s.keyword_candidates, where),
            )
            for kind, rows in (("vector", vres), ("keyword", kres)):
                for rank, row in enumerate(rows, start=1):
                    c = cands.setdefault(row["id"], _Cand(row=row))
                    c.rrf += 1.0 / (self.s.rrf_k + rank)
                    c.queries.add(q)
                    if kind == "vector":
                        c.vector_rank = rank if c.vector_rank is None else min(c.vector_rank, rank)
                    else:
                        c.keyword_rank = rank if c.keyword_rank is None else min(c.keyword_rank, rank)
        return cands

    async def search(self, queries: str | list[str], *, where: str | None = None, top_k: int | None = None,
                     rerank: bool = True, rerank_query: str | None = None) -> list[RetrievedChunk]:
        queries = [queries] if isinstance(queries, str) else [q for q in dict.fromkeys(queries) if q.strip()]
        if not queries:
            return []
        top_k = top_k or self.s.final_top_k
        cands = await self._candidates(queries, where)
        if not cands:
            return []
        fused = sorted(cands.values(), key=lambda c: c.rrf, reverse=True)[: self.s.rerank_candidates]
        max_rrf = fused[0].rrf

        rq = rerank_query or queries[0]
        rerank_scores: list[float | None] = [None] * len(fused)
        if rerank and self.reranker.name != "none":
            texts = [f"{c.row['doc_title']}\n{c.row['text']}" for c in fused]
            rerank_scores = await self.reranker.score(rq, texts)
        for c, rs in zip(fused, rerank_scores, strict=True):
            c.row["_rerank"] = rs
            c.row["_final"] = (0.8 * rs + 0.2 * c.rrf / max_rrf) if rs is not None else c.rrf / max_rrf

        ranked = sorted(fused, key=lambda c: c.row["_final"], reverse=True)
        selected = self._mmr(ranked, top_k)
        return await asyncio.to_thread(self._finalize, selected)

    def _mmr(self, ranked: list[_Cand], k: int) -> list[_Cand]:
        lam = self.s.mmr_lambda
        if lam >= 1 or len(ranked) <= k:
            return ranked[:k]
        toks = {c.row["id"]: _tokens(c.row["text"]) for c in ranked}
        chosen: list[_Cand] = []
        pool = list(ranked)
        while pool and len(chosen) < k:
            best = max(pool, key=lambda c: lam * c.row["_final"] - (1 - lam) * max(
                (_jaccard(toks[c.row["id"]], toks[s.row["id"]]) for s in chosen), default=0.0))
            chosen.append(best)
            pool.remove(best)
        return chosen

    def _finalize(self, selected: list[_Cand]) -> list[RetrievedChunk]:
        out = []
        n = self.s.neighbor_expansion
        nb: dict[tuple[str, int], str] = {}
        if n:
            wanted: dict[str, list[int]] = {}
            for c in selected:
                o = c.row["ordinal"]
                wanted.setdefault(c.row["doc_id"], []).extend(x for x in range(o - n, o + n + 1) if x != o and x >= 0)
            nb = self.store.neighbors_many(wanted)
        for c in selected:
            r = c.row
            before = after = ""
            if n:
                doc, o = r["doc_id"], r["ordinal"]
                before = "\n\n".join(nb[(doc, x)] for x in range(o - n, o) if (doc, x) in nb)
                after = "\n\n".join(nb[(doc, x)] for x in range(o + 1, o + n + 1) if (doc, x) in nb)
            out.append(RetrievedChunk(
                chunk=row_to_chunk(r), doc_title=r["doc_title"], source=r["source"], scope=r.get("scope") or "kb",
                date=r.get("date") or "", score=round(float(r["_final"]), 4), vector_rank=c.vector_rank,
                keyword_rank=c.keyword_rank, rerank_score=None if r["_rerank"] is None else round(float(r["_rerank"]), 4),
                matched_queries=sorted(c.queries), context_before=before, context_after=after,
            ))
        return out
