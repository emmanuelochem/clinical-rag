"""Core data types shared across ingestion, retrieval and the API."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Block(BaseModel):
    """A structural unit produced by a parser (paragraph, heading, table, code, list)."""

    kind: Literal["heading", "paragraph", "table", "code", "list"] = "paragraph"
    text: str
    level: int = 0  # heading level (1..6); 0 for non-headings
    page: int | None = None


class ParsedDocument(BaseModel):
    title: str
    blocks: list[Block]
    source: str  # filename or URL
    mime: str


class Chunk(BaseModel):
    id: str
    doc_id: str
    ordinal: int  # position of the chunk within its document
    text: str  # raw chunk text, shown to users and the LLM
    headings: list[str] = Field(default_factory=list)  # heading breadcrumb
    page_start: int | None = None
    page_end: int | None = None
    kind: str = "text"  # "text" | "table"

    def contextual_text(self, doc_title: str) -> str:
        """Text used for embedding/keyword indexing: prefixes the chunk with its document
        title and section breadcrumb so isolated chunks keep their context."""
        crumb = " > ".join([doc_title, *self.headings])
        return f"{crumb}\n\n{self.text}"


class RetrievedChunk(BaseModel):
    chunk: Chunk
    doc_title: str
    source: str
    scope: str = "kb"  # "kb" (medical reference) or "patient" (clinical note)
    date: str = ""  # note date for patient chunks
    score: float = 0.0  # final score after fusion / reranking
    vector_rank: int | None = None
    keyword_rank: int | None = None
    rerank_score: float | None = None
    matched_queries: list[str] = Field(default_factory=list)
    context_before: str = ""
    context_after: str = ""


class DocumentInfo(BaseModel):
    id: str
    title: str
    source: str
    mime: str
    size_bytes: int
    status: Literal["pending", "processing", "ready", "error"]
    error: str | None = None
    num_chunks: int = 0
    created_at: str
    has_file: bool = False
    scope: str = "kb"
    patient_id: str | None = None


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatRequest(BaseModel):
    message: str
    history: list[ChatMessage] = Field(default_factory=list)
    mode: Literal["fast", "agentic"] = "agentic"
    patient_id: str | None = None  # scope the assistant to one patient's record
    doc_ids: list[str] | None = None  # restrict retrieval to these documents
    top_k: int | None = None


class SearchRequest(BaseModel):
    query: str
    scope: Literal["kb", "patient"] | None = None
    patient_id: str | None = None
    doc_ids: list[str] | None = None
    top_k: int | None = None
    rerank: bool = True


class UrlIngestRequest(BaseModel):
    url: str


class DifferentialRequest(BaseModel):
    patient_id: str
    symptoms: list[str]
    notes: str = ""  # free-text presentation details (onset, duration, severity...)
