"""Structure-aware parsers. Each returns a ParsedDocument made of typed blocks
(headings, paragraphs, tables, code, lists) so the chunker can respect document structure."""

from __future__ import annotations

import csv
import io
import re
from collections import Counter
from pathlib import Path

from app.models import Block, ParsedDocument

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".html", ".htm", ".md", ".markdown", ".txt", ".csv"}


class UnsupportedFormat(ValueError):
    pass


def _clean(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\u00ad", "")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def rows_to_markdown(rows: list[list[str]]) -> str:
    rows = [[_clean(str(c or "")).replace("|", "\\|").replace("\n", " ") for c in r] for r in rows if any(c for c in r)]
    if not rows:
        return ""
    width = max(len(r) for r in rows)
    rows = [r + [""] * (width - len(r)) for r in rows]
    lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
    lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
    return "\n".join(lines)


# --------------------------------------------------------------------------- PDF


def parse_pdf(data: bytes, source: str) -> ParsedDocument:
    import pymupdf

    doc = pymupdf.open(stream=data, filetype="pdf")
    pages = []
    size_counter: Counter[float] = Counter()

    for pno, page in enumerate(doc, start=1):
        tables = []
        try:
            for t in page.find_tables().tables:
                md = rows_to_markdown(t.extract())
                if md:
                    tables.append((pymupdf.Rect(t.bbox), md))
        except Exception:
            pass
        lines = []
        for b in page.get_text("dict", flags=pymupdf.TEXTFLAGS_TEXT)["blocks"]:
            if b.get("type") != 0:
                continue
            bbox = pymupdf.Rect(b["bbox"])
            if any(bbox.intersects(r) and (bbox & r).get_area() > 0.5 * bbox.get_area() for r, _ in tables):
                continue  # text belongs to a table we extract separately
            for ln in b["lines"]:
                text = "".join(s["text"] for s in ln["spans"])
                if not text.strip():
                    continue
                size = round(max(s["size"] for s in ln["spans"]), 1)
                bold = all(s["flags"] & 16 for s in ln["spans"] if s["text"].strip())
                size_counter[size] += len(text)
                lines.append({"text": text, "size": size, "bold": bold, "y": ln["bbox"][1], "block": id(b)})
        pages.append((pno, lines, tables))

    body = size_counter.most_common(1)[0][0] if size_counter else 10.0
    heading_sizes = sorted({sz for sz in size_counter if sz >= body * 1.15}, reverse=True)[:5]
    level_of = {sz: i + 1 for i, sz in enumerate(heading_sizes)}

    title = (doc.metadata or {}).get("title") or ""
    blocks: list[Block] = []
    for pno, lines, tables in pages:
        para: list[str] = []
        last_block = None

        def flush():
            if para:
                text = _clean(" ".join(para))
                text = re.sub(r"(\w)- (\w)", r"\1\2", text)  # de-hyphenate line breaks
                if text:
                    blocks.append(Block(kind="paragraph", text=text, page=pno))
                para.clear()

        table_queue = sorted(tables, key=lambda t: t[0].y0)
        for ln in lines:
            while table_queue and table_queue[0][0].y0 < ln["y"]:
                flush()
                blocks.append(Block(kind="table", text=table_queue.pop(0)[1], page=pno))
            text = ln["text"].strip()
            is_heading = len(text) < 140 and (
                ln["size"] in level_of or (ln["bold"] and ln["size"] >= body and len(text) < 90 and not text.endswith("."))
            )
            if is_heading and not re.fullmatch(r"[\d\W]+", text):
                flush()
                level = level_of.get(ln["size"], len(heading_sizes) + 1)
                if blocks and blocks[-1].kind == "heading" and blocks[-1].page == pno and blocks[-1].level == level:
                    blocks[-1].text += " " + text  # multi-line heading
                else:
                    blocks.append(Block(kind="heading", text=text, level=min(level, 6), page=pno))
                last_block = None
                continue
            if last_block is not None and ln["block"] != last_block:
                flush()
            para.append(text)
            last_block = ln["block"]
        flush()
        for _, md in table_queue:
            blocks.append(Block(kind="table", text=md, page=pno))

    if not title:
        first_h = next((b.text for b in blocks if b.kind == "heading"), None)
        title = first_h or Path(source).stem
    if not any(b.text for b in blocks):
        raise ValueError("No extractable text found (the PDF may be scanned images; OCR is not enabled).")
    return ParsedDocument(title=_clean(title), blocks=blocks, source=source, mime="application/pdf")


# --------------------------------------------------------------------------- DOCX


def parse_docx(data: bytes, source: str) -> ParsedDocument:
    import docx
    from docx.table import Table
    from docx.text.paragraph import Paragraph

    d = docx.Document(io.BytesIO(data))
    blocks: list[Block] = []
    for el in d.element.body.iterchildren():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag == "p":
            p = Paragraph(el, d)
            text = _clean(p.text)
            if not text:
                continue
            style = (p.style.name if p.style is not None else "") or ""
            m = re.match(r"Heading (\d)", style)
            if style == "Title":
                blocks.append(Block(kind="heading", text=text, level=1))
            elif m:
                blocks.append(Block(kind="heading", text=text, level=int(m.group(1))))
            elif "List" in style:
                blocks.append(Block(kind="list", text=f"- {text}"))
            else:
                blocks.append(Block(kind="paragraph", text=text))
        elif tag == "tbl":
            t = Table(el, d)
            md = rows_to_markdown([[c.text for c in r.cells] for r in t.rows])
            if md:
                blocks.append(Block(kind="table", text=md))
    title = d.core_properties.title or next((b.text for b in blocks if b.kind == "heading"), Path(source).stem)
    return ParsedDocument(title=title, blocks=blocks, source=source, mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document")


# --------------------------------------------------------------------------- HTML


def parse_html(data: bytes | str, source: str) -> ParsedDocument:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(data, "lxml")
    title = _clean(soup.title.get_text()) if soup.title else ""
    for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "iframe", "button"]):
        tag.decompose()
    root = soup.find("main") or soup.find("article") or soup.body or soup
    blocks: list[Block] = []

    def walk(node):
        for child in getattr(node, "children", []):
            name = getattr(child, "name", None)
            if name is None:
                continue
            if re.fullmatch(r"h[1-6]", name):
                text = _clean(child.get_text(" "))
                if text:
                    blocks.append(Block(kind="heading", text=text, level=int(name[1])))
            elif name == "table":
                rows = [[c.get_text(" ") for c in tr.find_all(["th", "td"])] for tr in child.find_all("tr")]
                md = rows_to_markdown(rows)
                if md:
                    blocks.append(Block(kind="table", text=md))
            elif name == "pre":
                blocks.append(Block(kind="code", text="```\n" + child.get_text().strip("\n") + "\n```"))
            elif name in ("ul", "ol"):
                items = [_clean(li.get_text(" ")) for li in child.find_all("li", recursive=False)]
                items = [i for i in items if i]
                if items:
                    blocks.append(Block(kind="list", text="\n".join(f"- {i}" for i in items)))
            elif name in ("p", "blockquote", "dd", "dt", "figcaption"):
                text = _clean(child.get_text(" "))
                if text:
                    blocks.append(Block(kind="paragraph", text=text))
            else:
                before = len(blocks)
                walk(child)
                # Leaf containers (e.g. <div>text</div>) with no structured children.
                if len(blocks) == before and name in ("div", "section", "span", "td", "li"):
                    text = _clean(child.get_text(" "))
                    if text and len(text) > 1:
                        blocks.append(Block(kind="paragraph", text=text))

    walk(root)
    if not title:
        title = next((b.text for b in blocks if b.kind == "heading"), source)
    return ParsedDocument(title=title, blocks=blocks, source=source, mime="text/html")


# --------------------------------------------------------------------------- Markdown / text / CSV


def parse_markdown(text: str, source: str, mime: str = "text/markdown") -> ParsedDocument:
    blocks: list[Block] = []
    lines = text.replace("\r\n", "\n").split("\n")
    i, para = 0, []

    def flush():
        if para:
            t = _clean(" ".join(para))
            if t:
                blocks.append(Block(kind="paragraph", text=t))
            para.clear()

    while i < len(lines):
        line = lines[i]
        if m := re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", line):
            flush()
            blocks.append(Block(kind="heading", text=m.group(2), level=len(m.group(1))))
        elif line.strip().startswith("```") or line.strip().startswith("~~~"):
            flush()
            fence, code = line.strip()[:3], [line]
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                code.append(lines[i])
                i += 1
            code.append(fence)
            blocks.append(Block(kind="code", text="\n".join(code)))
        elif line.lstrip().startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i].strip())
                i += 1
            blocks.append(Block(kind="table", text="\n".join(rows)))
            continue
        elif re.match(r"^\s*([-*+]|\d+[.)])\s+", line):
            flush()
            items = []
            while i < len(lines) and (re.match(r"^\s*([-*+]|\d+[.)])\s+", lines[i]) or (lines[i].startswith("  ") and items)):
                items.append(lines[i].rstrip())
                i += 1
            blocks.append(Block(kind="list", text="\n".join(items)))
            continue
        elif not line.strip():
            flush()
        else:
            para.append(line.strip())
        i += 1
    flush()
    title = next((b.text for b in blocks if b.kind == "heading" and b.level == 1), Path(source).stem)
    return ParsedDocument(title=title, blocks=blocks, source=source, mime=mime)


def parse_csv(text: str, source: str) -> ParsedDocument:
    rows = list(csv.reader(io.StringIO(text)))
    if not rows:
        raise ValueError("Empty CSV")
    header, body = rows[0], rows[1:]
    blocks = [Block(kind="table", text=rows_to_markdown([header, *body[i : i + 25]])) for i in range(0, max(len(body), 1), 25)]
    return ParsedDocument(title=Path(source).stem, blocks=blocks, source=source, mime="text/csv")


def _decode(data: bytes) -> str:
    for enc in ("utf-8-sig", "utf-16", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def parse_bytes(data: bytes, filename: str) -> ParsedDocument:
    ext = Path(filename).suffix.lower()
    if ext == ".pdf":
        return parse_pdf(data, filename)
    if ext == ".docx":
        return parse_docx(data, filename)
    if ext in (".html", ".htm"):
        return parse_html(data, filename)
    if ext in (".md", ".markdown"):
        return parse_markdown(_decode(data), filename)
    if ext == ".txt":
        return parse_markdown(_decode(data), filename, mime="text/plain")
    if ext == ".csv":
        return parse_csv(_decode(data), filename)
    raise UnsupportedFormat(f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}")
