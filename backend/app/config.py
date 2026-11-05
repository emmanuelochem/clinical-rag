"""Application settings, loaded from environment variables (prefix ``RAG_``) or a ``.env`` file.

Model settings left empty are filled from the selected provider's preset, so the minimal
configuration is just an API key:

    RAG_LLM_PROVIDER=groq        # groq (default) | gemini | openai_compatible | ollama
    GROQ_API_KEY=gsk_...         # or GEMINI_API_KEY=... for Gemini
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["groq", "gemini", "openai_compatible", "ollama"]

# base_url, chat model, planner model (smaller/faster; used for planning, reflection, LLM rerank).
# Model IDs change over time: GET /api/health lists the provider's live models and flags missing ones.
LLM_PRESETS: dict[str, tuple[str, str, str]] = {
    "groq": ("https://api.groq.com/openai/v1", "openai/gpt-oss-120b", "openai/gpt-oss-20b"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-flash-latest", "gemini-flash-lite-latest"),
    "openai_compatible": ("", "", ""),  # e.g. OpenRouter, Mistral, NVIDIA NIM: set base URL + models
    "ollama": ("http://localhost:11434", "qwen2.5:7b-instruct", ""),
}

# model, query prefix, document prefix
EMBED_PRESETS: dict[str, tuple[str, str, str]] = {
    "local": ("BAAI/bge-small-en-v1.5", "Represent this sentence for searching relevant passages: ", ""),
    "ollama": ("nomic-embed-text", "search_query: ", "search_document: "),
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="RAG_", env_file=("../.env", ".env"), extra="ignore", populate_by_name=True)

    # --- Storage -----------------------------------------------------------
    data_dir: Path = Path("./data")

    # --- Chat LLM ----------------------------------------------------------
    llm_provider: LLMProvider = "groq"
    llm_base_url: str = ""
    llm_api_key: str = ""  # generic key for openai_compatible providers
    groq_api_key: str = Field("", validation_alias=AliasChoices("RAG_GROQ_API_KEY", "GROQ_API_KEY"))
    gemini_api_key: str = Field("", validation_alias=AliasChoices("RAG_GEMINI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"))
    chat_model: str = ""
    planner_model: str = ""
    # Optional "low" | "medium" | "high" for reasoning models (e.g. gpt-oss on Groq). Empty = provider default.
    reasoning_effort: str = ""
    max_output_tokens: int = 2048
    max_retries: int = 4  # retries on rate limits (429) and transient 5xx, honouring Retry-After
    temperature: float = 0.1
    request_timeout: float = 120.0

    # Ollama-only
    ollama_url: str = "http://localhost:11434"
    num_ctx: int = 8192

    # --- Embeddings --------------------------------------------------------
    embed_provider: Literal["local", "ollama"] = "local"
    embed_model: str = ""
    # Task prefixes for asymmetric embedding models. None = use the preset's.
    embed_query_prefix: str | None = None
    embed_doc_prefix: str | None = None
    embed_batch_size: int = 32

    # --- Chunking ----------------------------------------------------------
    chunk_tokens: int = 350
    chunk_overlap_tokens: int = 60

    # --- Retrieval ---------------------------------------------------------
    vector_candidates: int = 30
    keyword_candidates: int = 30
    rrf_k: int = 60
    reranker: Literal["cross-encoder", "llm", "none"] = "cross-encoder"
    cross_encoder_model: str = "Xenova/ms-marco-MiniLM-L-6-v2"
    rerank_candidates: int = 24
    final_top_k: int = 8
    # Maximal marginal relevance diversity (0 = pure diversity, 1 = pure relevance).
    mmr_lambda: float = 0.75
    neighbor_expansion: int = 1  # attach N adjacent chunks as context around each hit

    # --- Agent -------------------------------------------------------------
    max_agent_rounds: int = 3
    max_subqueries: int = 4

    # --- Ingestion ---------------------------------------------------------
    max_upload_mb: int = 50
    url_fetch_timeout: float = 20.0

    cors_origins: list[str] = ["http://localhost:3000"]
    # Extra allowed browser origins as a regex, e.g. Vercel production + preview URLs:
    #   https://clinical-rag[a-z0-9-]*\.vercel\.app
    cors_origin_regex: str = ""
    # ONNX Runtime threads for local embeddings/reranking (0 = auto). Use 1 on tiny shared CPUs.
    onnx_threads: int = 0

    # Optional shared secret for /api/keepalive (?token=...). Empty = open endpoint (it only warms caches).
    keepalive_token: str = ""

    @model_validator(mode="after")
    def _apply_presets(self) -> "Settings":
        base, chat, planner = LLM_PRESETS[self.llm_provider]
        if self.llm_provider == "ollama":
            base = self.ollama_url
        self.llm_base_url = (self.llm_base_url or base).rstrip("/")
        self.chat_model = self.chat_model or chat
        self.planner_model = self.planner_model or planner
        emb, qp, dp = EMBED_PRESETS[self.embed_provider]
        if not self.embed_model:
            self.embed_model = emb
        elif self.embed_model != emb and self.embed_query_prefix is None:
            qp = dp = ""  # custom model: no prefixes unless explicitly configured
        if self.embed_query_prefix is None:
            self.embed_query_prefix = qp
        if self.embed_doc_prefix is None:
            self.embed_doc_prefix = dp
        return self

    @property
    def api_key(self) -> str:
        return {"groq": self.groq_api_key, "gemini": self.gemini_api_key}.get(self.llm_provider, "") or self.llm_api_key

    @property
    def planner(self) -> str:
        return self.planner_model or self.chat_model

    @property
    def embed_id(self) -> str:
        """Identity of the embedding space; vectors from different models can't be mixed."""
        return f"{self.embed_provider}:{self.embed_model}"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def models_dir(self) -> Path:
        return self.data_dir / "models"


@lru_cache
def get_settings() -> Settings:
    s = Settings()
    s.data_dir.mkdir(parents=True, exist_ok=True)
    s.uploads_dir.mkdir(parents=True, exist_ok=True)
    return s
