"""LanceDB-backed chunk index with dense-vector and BM25 full-text search.

One table holds every chunk. ``scope`` separates the medical knowledge base ("kb")
from patient clinical notes ("patient"); patient chunks carry ``patient_id`` so
retrieval can be hard-filtered to a single patient's record.
"""

from __future__ import annotations

import json
import re
import threading
from pathlib import Path

import lancedb
import pyarrow as pa
from lancedb.index import FTS

from app.models import Chunk

TABLE = "chunks"


def _quote(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"


def build_filter(scope: str | None = None, patient_id: str | None = None, doc_ids: list[str] | None = None) -> str | None:
    parts = []
    if scope:
        parts.append(f"scope = {_quote(scope)}")
    if patient_id:
        parts.append(f"patient_id = {_quote(patient_id)}")
    if doc_ids:
        parts.append(f"doc_id IN ({', '.join(_quote(d) for d in doc_ids)})")
    return " AND ".join(parts) or None


_FTS_STRIP = re.compile(r"[^\w\s-]", re.UNICODE)


def sanitize_fts(q: str) -> str:
    """Strip query-syntax characters so arbitrary user text can't break the FTS parser."""
    q = _FTS_STRIP.sub(" ", q)
    return " ".join(w for w in q.split() if w.lower() not in {"and", "or", "not"})


class EmbeddingMismatch(RuntimeError):
    pass


class VectorStore:
    def __init__(self, path: Path, embed_id: str = ""):
        path.mkdir(parents=True, exist_ok=True)
        self.db = lancedb.connect(str(path))
        self._lock = threading.Lock()
        self._table = None
        self._fts_dirty = False
        self.embed_id = embed_id
        self._meta_path = path / "embedding.json"
        self.mismatch: str | None = None
        if TABLE in self.db.table_names():
            self._table = self.db.open_table(TABLE)
            built_with = self._read_meta()
            if built_with is None:
                self._write_meta()
            elif embed_id and built_with != embed_id:
                self.mismatch = (
                    f"The search index was built with embeddings '{built_with}' but the app is configured for "
                    f"'{embed_id}'. Vectors from different models can't be mixed. Re-index with "
                    "`python -m app.seed --wipe-all`, or set RAG_EMBED_PROVIDER / RAG_EMBED_MODEL back."
                )

    def _read_meta(self) -> str | None:
        try:
            return json.loads(self._meta_path.read_text())["embed_id"]
        except (FileNotFoundError, KeyError, json.JSONDecodeError):
            return None

    def _write_meta(self) -> None:
        if self.embed_id:
            self._meta_path.write_text(json.dumps({"embed_id": self.embed_id}))

    def _check(self) -> None:
        if self.mismatch:
            raise EmbeddingMismatch(self.mismatch)

    def _schema(self, dim: int) -> pa.Schema:
        return pa.schema(
            [
                ("id", pa.string()), ("doc_id", pa.string()), ("scope", pa.string()), ("patient_id", pa.string()),
                ("ordinal", pa.int32()), ("text", pa.string()), ("index_text", pa.string()),
                ("headings", pa.string()), ("page_start", pa.int32()), ("page_end", pa.int32()),
                ("kind", pa.string()), ("doc_title", pa.string()), ("source", pa.string()),
                ("date", pa.string()), ("vector", pa.list_(pa.float32(), dim)),
            ]
        )

    @property
    def ready(self) -> bool:
        return self._table is not None and self._table.count_rows() > 0

    def add(self, chunks: list[Chunk], vectors: list[list[float]], *, doc_title: str, source: str,
            scope: str, patient_id: str = "", date: str = "") -> None:
        if not chunks:
            return
        self._check()
        rows = [
            {
                "id": c.id, "doc_id": c.doc_id, "scope": scope, "patient_id": patient_id, "ordinal": c.ordinal,
                "text": c.text, "index_text": c.contextual_text(doc_title), "headings": json.dumps(c.headings),
                "page_start": c.page_start, "page_end": c.page_end, "kind": c.kind,
                "doc_title": doc_title, "source": source, "date": date, "vector": v,
            }
            for c, v in zip(chunks, vectors, strict=True)
        ]
        with self._lock:
            if self._table is None:
                self._table = self.db.create_table(TABLE, schema=self._schema(len(vectors[0])), exist_ok=True)
                self._write_meta()
            dim = self._table.schema.field("vector").type.list_size
            if dim != len(vectors[0]):
                raise EmbeddingMismatch(f"Embedding size {len(vectors[0])} does not match the index ({dim}). "
                                        "Re-index with `python -m app.seed --wipe-all`.")
            self._table.add(rows)
            self._fts_dirty = True

    def delete_doc(self, doc_id: str) -> None:
        with self._lock:
            if self._table is not None:
                self._table.delete(f"doc_id = {_quote(doc_id)}")
                self._fts_dirty = True

    def refresh_fts(self) -> None:
        with self._lock:
            if self._table is not None and self._fts_dirty:
                self._table.create_index("index_text", config=FTS(stem=True, remove_stop_words=True), replace=True)
                self._fts_dirty = False

    def vector_search(self, vec: list[float], k: int, where: str | None) -> list[dict]:
        self._check()
        if not self.ready:
            return []
        q = self._table.search(vec, query_type="vector").metric("cosine").limit(k)
        if where:
            q = q.where(where, prefilter=True)
        return q.select(_COLS + ["_distance"]).to_list()

    def keyword_search(self, query: str, k: int, where: str | None) -> list[dict]:
        if not self.ready:
            return []
        self.refresh_fts()
        query = sanitize_fts(query)
        if not query:
            return []
        q = self._table.search(query, query_type="fts").limit(k)
        if where:
            q = q.where(where, prefilter=True)
        try:
            return q.select(_COLS + ["_score"]).to_list()
        except Exception:
            return []

    def neighbors(self, doc_id: str, ordinals: list[int]) -> dict[int, str]:
        if not self.ready or not ordinals:
            return {}
        where = f"doc_id = {_quote(doc_id)} AND ordinal IN ({', '.join(map(str, ordinals))})"
        rows = self._table.search().where(where).select(["ordinal", "text"]).limit(len(ordinals)).to_list()
        return {r["ordinal"]: r["text"] for r in rows}

    def neighbors_many(self, wanted: dict[str, list[int]]) -> dict[tuple[str, int], str]:
        """Fetch adjacent chunks for many documents in ONE query (one scan instead of one per hit,
        which matters on small shared CPUs). Returns {(doc_id, ordinal): text}."""
        wanted = {d: sorted(set(o)) for d, o in wanted.items() if o}
        if not self.ready or not wanted:
            return {}
        where = " OR ".join(
            f"(doc_id = {_quote(d)} AND ordinal IN ({', '.join(map(str, o))}))" for d, o in wanted.items())
        limit = sum(len(o) for o in wanted.values())
        rows = self._table.search().where(where).select(["doc_id", "ordinal", "text"]).limit(limit).to_list()
        return {(r["doc_id"], r["ordinal"]): r["text"] for r in rows}

    def doc_chunks(self, doc_id: str) -> list[dict]:
        if not self.ready:
            return []
        rows = self._table.search().where(f"doc_id = {_quote(doc_id)}").select(_COLS).limit(100_000).to_list()
        return sorted(rows, key=lambda r: r["ordinal"])


_COLS = ["id", "doc_id", "scope", "patient_id", "ordinal", "text", "headings", "page_start", "page_end",
         "kind", "doc_title", "source", "date"]


def row_to_chunk(r: dict) -> Chunk:
    return Chunk(
        id=r["id"], doc_id=r["doc_id"], ordinal=r["ordinal"], text=r["text"],
        headings=json.loads(r.get("headings") or "[]"), page_start=r.get("page_start"),
        page_end=r.get("page_end"), kind=r.get("kind") or "text",
    )
