"""Ingestion: parse -> chunk -> embed -> index, for knowledge-base documents and patient notes."""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path

import httpx

from app.config import Settings
from app.ingest.chunker import chunk_document
from app.ingest.parsers import parse_bytes, parse_html, parse_markdown
from app.models import ParsedDocument
from app.providers.embeddings import Embedder
from app.store.db import Database, now_iso
from app.store.vectors import VectorStore

log = logging.getLogger(__name__)


def doc_id_for(content: bytes, name: str) -> str:
    return hashlib.sha256(name.encode() + b"\0" + content).hexdigest()[:16]


class Ingestor:
    def __init__(self, settings: Settings, db: Database, store: VectorStore, embedder: Embedder):
        self.s, self.db, self.store, self.embedder = settings, db, store, embedder

    # ------------------------------------------------------------------ registry

    def register(self, doc_id: str, *, title: str, source: str, mime: str, size: int,
                 file_path: str | None = None, scope: str = "kb", patient_id: str | None = None) -> None:
        with self.db.tx() as c:
            c.execute(
                "INSERT OR REPLACE INTO documents (id, title, source, mime, size_bytes, status, error, num_chunks,"
                " created_at, file_path, scope, patient_id) VALUES (?, ?, ?, ?, ?, 'pending', NULL, 0, ?, ?, ?, ?)",
                (doc_id, title, source, mime, size, now_iso(), file_path, scope, patient_id),
            )

    def _status(self, doc_id: str, status: str, **fields) -> None:
        sets = ", ".join(["status = ?"] + [f"{k} = ?" for k in fields])
        with self.db.tx() as c:
            c.execute(f"UPDATE documents SET {sets} WHERE id = ?", (status, *fields.values(), doc_id))

    # ------------------------------------------------------------------ indexing

    async def index_parsed(self, doc: ParsedDocument, doc_id: str, *, scope: str = "kb",
                           patient_id: str = "", date: str = "") -> int:
        chunks = chunk_document(doc, doc_id, self.s.chunk_tokens, self.s.chunk_overlap_tokens)
        if not chunks:
            raise ValueError("Document produced no indexable text.")
        vectors = await self.embedder.embed_documents([c.contextual_text(doc.title) for c in chunks])
        self.store.delete_doc(doc_id)  # idempotent re-ingest
        self.store.add(chunks, vectors, doc_title=doc.title, source=doc.source, scope=scope,
                       patient_id=patient_id, date=date)
        return len(chunks)

    async def ingest_file(self, doc_id: str, data: bytes, filename: str) -> None:
        self._status(doc_id, "processing")
        try:
            doc = parse_bytes(data, filename)
            n = await self.index_parsed(doc, doc_id)
            self.store.refresh_fts()
            self._status(doc_id, "ready", num_chunks=n, title=doc.title, mime=doc.mime)
        except Exception as e:
            log.exception("Ingestion failed for %s", filename)
            self._status(doc_id, "error", error=str(e)[:500])

    async def fetch_url(self, url: str) -> tuple[bytes, str, str]:
        if not re.match(r"^https?://", url):
            raise ValueError("URL must start with http:// or https://")
        async with httpx.AsyncClient(follow_redirects=True, timeout=self.s.url_fetch_timeout,
                                     headers={"User-Agent": "clinical-rag-ingestor/1.0"}) as c:
            r = await c.get(url)
            r.raise_for_status()
        ctype = r.headers.get("content-type", "").split(";")[0].strip()
        ext = {"application/pdf": ".pdf", "text/markdown": ".md", "text/plain": ".txt",
               "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx"}.get(ctype, ".html")
        name = Path(httpx.URL(url).path).name or "page"
        if not name.endswith(ext):
            name += ext
        return r.content, name, ctype

    async def ingest_url(self, doc_id: str, url: str) -> None:
        self._status(doc_id, "processing")
        try:
            data, name, _ = await self.fetch_url(url)
            doc = parse_bytes(data, name)
            doc.source = url
            n = await self.index_parsed(doc, doc_id)
            self.store.refresh_fts()
            self._status(doc_id, "ready", num_chunks=n, title=doc.title, mime=doc.mime, size_bytes=len(data))
        except Exception as e:
            log.exception("URL ingestion failed for %s", url)
            self._status(doc_id, "error", error=str(e)[:500])

    async def index_patient_notes(self, patient_id: str | None = None) -> int:
        """Embed and index clinical notes (all patients, or one)."""
        sql = "SELECT n.*, p.first_name, p.last_name FROM notes n JOIN patients p ON p.id = n.patient_id"
        notes = self.db.query(sql + (" WHERE n.patient_id = ?" if patient_id else ""), (patient_id,) if patient_id else ())
        total = 0
        for n in notes:
            title = f"{n['type']} — {n['date']} — {n['first_name']} {n['last_name']}"
            doc = parse_markdown(n["text"], source=f"note:{n['id']}")
            doc.title = title
            total += await self.index_parsed(doc, n["id"], scope="patient", patient_id=n["patient_id"], date=n["date"])
        self.store.refresh_fts()
        return total

    def delete(self, doc_id: str) -> None:
        row = self.db.one("SELECT file_path FROM documents WHERE id = ?", (doc_id,))
        self.store.delete_doc(doc_id)
        with self.db.tx() as c:
            c.execute("DELETE FROM documents WHERE id = ?", (doc_id,))
        if row and row.get("file_path"):
            Path(row["file_path"]).unlink(missing_ok=True)


def parse_medlineplus_xml(data: bytes, wanted: set[str] | None = None) -> list[ParsedDocument]:
    """Parse the MedlinePlus Health Topics XML (public domain, U.S. National Library of Medicine;
    download from https://medlineplus.gov/xml.html) into documents, one per English topic."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(data)
    docs = []
    for t in root.iter("health-topic"):
        if t.get("language", "English") != "English":
            continue
        title = t.get("title", "")
        if wanted and not any(w.lower() in title.lower() for w in wanted):
            continue
        summary = t.findtext("full-summary") or ""
        also = [a.text for a in t.findall("also-called") if a.text]
        html = f"<h1>{title}</h1>" + (f"<p>Also called: {', '.join(also)}</p>" if also else "") + summary
        doc = parse_html(html, t.get("url", title))
        doc.title = f"MedlinePlus: {title}"
        docs.append(doc)
    return docs
