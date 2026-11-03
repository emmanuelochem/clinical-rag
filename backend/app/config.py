"""Application settings, loaded from environment variables (prefix ``RAG_``) or a ``.env`` file."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=".env", extra="ignore")

    # --- Storage -----------------------------------------------------------
    data_dir: Path = Path("./data")

    # --- Ollama ------------------------------------------------------------
    ollama_url: str = "http://localhost:11434"
    chat_model: str = "qwen2.5:7b-instruct"
    # Smaller/faster model for planning, query rewriting and sufficiency checks.
    # Falls back to chat_model when empty.
    planner_model: str = ""
    embed_model: str = "nomic-embed-text"
    # Task prefixes for asymmetric embedding models (nomic, e5, bge...). Empty to disable.
    embed_query_prefix: str = "search_query: "
    embed_doc_prefix: str = "search_document: "
    embed_batch_size: int = 32
    request_timeout: float = 300.0
    temperature: float = 0.1
    num_ctx: int = 8192

    # --- Chunking ----------------------------------------------------------
    chunk_tokens: int = 350
    chunk_overlap_tokens: int = 60

    # --- Retrieval ---------------------------------------------------------
    vector_candidates: int = 30
    keyword_candidates: int = 30
    rrf_k: int = 60
    reranker: Literal["cross-encoder", "llm", "none"] = "cross-encoder"
    cross_encoder_model: str = "BAAI/bge-reranker-base"
    rerank_candidates: int = 24
    final_top_k: int = 8
    # Maximal marginal relevance diversity (0 = pure relevance, 1 = pure diversity).
    mmr_lambda: float = 0.75
    neighbor_expansion: int = 1  # attach N adjacent chunks as context around each hit

    # --- Agent -------------------------------------------------------------
    max_agent_rounds: int = 3
    max_subqueries: int = 4

    # --- Ingestion ---------------------------------------------------------
    max_upload_mb: int = 50
    url_fetch_timeout: float = 20.0

    cors_origins: list[str] = ["http://localhost:3000"]

    @property
    def planner(self) -> str:
        return self.planner_model or self.chat_model

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.uploads_dir.mkdir(parents=True, exist_ok=True)
    return s
