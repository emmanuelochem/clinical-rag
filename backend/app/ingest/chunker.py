"""Structure-aware chunking.

* Chunks never cross a top-level section boundary (heading of level <= 2).
* Each chunk carries its heading breadcrumb, so retrieval and citations keep context.
* Tables are kept whole when they fit; large tables are split by rows with the header repeated.
* Oversized paragraphs are split on sentence boundaries; consecutive chunks overlap.
"""

from __future__ import annotations

import hashlib
import re

from app.models import Block, Chunk, ParsedDocument


def count_tokens(text: str) -> int:
    # Fast approximation (~0.75 words per token for English prose).
    return max(1, int(len(re.findall(r"\S+", text)) * 1.33))


_SENT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9(\"'])")


def _split_long(text: str, budget: int) -> list[str]:
    sents = _SENT_RE.split(text)
    out, cur = [], []
    for s in sents:
        if count_tokens(s) > budget:  # pathological sentence: hard-split on words
            words = s.split()
            step = max(1, int(budget / 1.33))
            out.extend(" ".join(words[i : i + step]) for i in range(0, len(words), step))
            continue
        if cur and count_tokens(" ".join(cur + [s])) > budget:
            out.append(" ".join(cur))
            cur = []
        cur.append(s)
    if cur:
        out.append(" ".join(cur))
    return out


def _split_table(md: str, budget: int) -> list[str]:
    lines = md.split("\n")
    if len(lines) <= 3 or count_tokens(md) <= budget:
        return [md]
    header, rows = lines[:2], lines[2:]
    out, cur = [], []
    for r in rows:
        if cur and count_tokens("\n".join(header + cur + [r])) > budget:
            out.append("\n".join(header + cur))
            cur = []
        cur.append(r)
    if cur:
        out.append("\n".join(header + cur))
    return out


def chunk_document(doc: ParsedDocument, doc_id: str, budget: int = 350, overlap: int = 60) -> list[Chunk]:
    chunks: list[Chunk] = []
    path: list[tuple[int, str]] = []  # (level, heading)
    buf: list[Block] = []

    def emit(texts: list[str], pages: list[int | None], kind: str = "text"):
        text = "\n\n".join(texts).strip()
        if not text:
            return
        pg = [p for p in pages if p is not None]
        ordinal = len(chunks)
        cid = hashlib.sha1(f"{doc_id}:{ordinal}:{text[:64]}".encode()).hexdigest()[:20]
        chunks.append(
            Chunk(
                id=cid, doc_id=doc_id, ordinal=ordinal, text=text, headings=[h for _, h in path],
                page_start=min(pg) if pg else None, page_end=max(pg) if pg else None, kind=kind,
            )
        )

    def flush():
        if not buf:
            return
        cur_texts: list[str] = []
        cur_pages: list[int | None] = []
        for b in buf:
            if b.kind == "table":
                if cur_texts:
                    emit(cur_texts, cur_pages)
                    cur_texts, cur_pages = [], []
                for part in _split_table(b.text, budget * 2):
                    emit([part], [b.page], kind="table")
                continue
            pieces = _split_long(b.text, budget) if count_tokens(b.text) > budget else [b.text]
            for piece in pieces:
                if cur_texts and count_tokens("\n\n".join(cur_texts + [piece])) > budget:
                    emit(cur_texts, cur_pages)
                    # Carry trailing context forward as overlap.
                    tail = " ".join(cur_texts[-1].split()[-int(overlap / 1.33) :]) if overlap else ""
                    cur_texts, cur_pages = ([f"…{tail}"] if tail else []), [cur_pages[-1]] if tail else []
                cur_texts.append(piece)
                cur_pages.append(b.page)
        if cur_texts and not (len(cur_texts) == 1 and cur_texts[0].startswith("…")):
            emit(cur_texts, cur_pages)
        buf.clear()

    for b in doc.blocks:
        if b.kind == "heading":
            flush()
            while path and path[-1][0] >= b.level:
                path.pop()
            path.append((b.level, b.text))
        else:
            buf.append(b)
    flush()
    return chunks
