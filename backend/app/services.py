"""Service container: builds and holds the application's long-lived components."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from app.agent.orchestrator import ClinicalAgent
from app.clinical.differential import DifferentialEngine
from app.clinical.repository import ClinicalRepo
from app.config import Settings
from app.ingest.pipeline import Ingestor
from app.providers.embeddings import Embedder, build_embedder
from app.providers.llm import LLM, build_llm
from app.providers.rerank import Reranker, build_reranker
from app.retrieval.hybrid import HybridRetriever
from app.store.db import Database
from app.store.vectors import VectorStore


@dataclass
class Services:
    settings: Settings
    db: Database
    store: VectorStore
    embedder: Embedder
    llm: LLM
    reranker: Reranker
    retriever: HybridRetriever
    repo: ClinicalRepo
    ingestor: Ingestor
    agent: ClinicalAgent
    differential: DifferentialEngine
    started_at: float = field(default_factory=time.monotonic)
    warmed_at: float | None = None

    async def warm_up(self) -> dict:
        """Load the embedding model, reranker and search index so the first real request is fast.

        Idempotent: after the first call it does nothing. Used by /api/keepalive (external cron)
        and at image build time to pre-download model weights.
        """
        if self.warmed_at is not None:
            return {"warmed_now": False, "warm_seconds": 0.0}
        t = time.monotonic()
        await self.embedder.embed_query("warm up")
        await self.reranker.score("warm up", ["warm up"])
        self.store.refresh_fts()
        self.warmed_at = time.monotonic()
        took = round(self.warmed_at - t, 2)
        logging.getLogger(__name__).info("Warm-up complete in %.2fs", took)
        return {"warmed_now": True, "warm_seconds": took}


def build_services(settings: Settings, *, embedder: Embedder | None = None, llm: LLM | None = None,
                   reranker: Reranker | None = None) -> Services:
    db = Database(settings.data_dir / "clinical.db")
    store = VectorStore(settings.data_dir / "lancedb", embed_id=settings.embed_id)
    embedder = embedder or build_embedder(settings)
    llm = llm or build_llm(settings)
    reranker = reranker or build_reranker(settings, llm)
    retriever = HybridRetriever(settings, store, embedder, reranker)
    repo = ClinicalRepo(db)
    return Services(
        settings=settings, db=db, store=store, embedder=embedder, llm=llm, reranker=reranker, retriever=retriever,
        repo=repo, ingestor=Ingestor(settings, db, store, embedder),
        agent=ClinicalAgent(settings, llm, retriever, repo),
        differential=DifferentialEngine(settings, llm, retriever, repo),
    )
