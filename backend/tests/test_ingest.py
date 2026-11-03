import io

from app.ingest.chunker import chunk_document, count_tokens
from app.ingest.parsers import parse_bytes, parse_html, parse_markdown


MD = """# Guide

Intro paragraph.

## Section A

""" + " ".join(f"Sentence number {i} about kidneys." for i in range(80)) + """

| Test | Value |
|---|---|
| eGFR | 52 |

## Section B

- item one
- item two
"""


def test_markdown_structure_and_chunking():
    doc = parse_markdown(MD, "guide.md")
    kinds = [b.kind for b in doc.blocks]
    assert doc.title == "Guide"
    assert {"heading", "paragraph", "table", "list"} <= set(kinds)
    chunks = chunk_document(doc, "d1", budget=100, overlap=20)
    assert len(chunks) > 3
    assert all(count_tokens(c.text) <= 140 for c in chunks if c.kind == "text")
    table = [c for c in chunks if c.kind == "table"]
    assert table and "eGFR" in table[0].text and table[0].headings == ["Guide", "Section A"]
    assert chunks[-1].headings == ["Guide", "Section B"]
    # overlap carries context between consecutive chunks in a section
    a_chunks = [c for c in chunks if c.headings == ["Guide", "Section A"] and c.kind == "text"]
    assert any(c.text.startswith("…") for c in a_chunks[1:])
    assert "Guide > Section A" in a_chunks[0].contextual_text("Guide")


def test_html_strips_boilerplate():
    html = b"<html><head><title>T</title><script>x()</script></head><body><nav>menu</nav><main><h1>Heart</h1><p>Body text.</p>" \
           b"<table><tr><th>A</th></tr><tr><td>1</td></tr></table></main><footer>foot</footer></body></html>"
    doc = parse_html(html, "x.html")
    text = " ".join(b.text for b in doc.blocks)
    assert "menu" not in text and "foot" not in text and "x()" not in text
    assert "Body text." in text and any(b.kind == "table" for b in doc.blocks)


def test_docx_and_pdf_parsing():
    import docx
    import pymupdf

    d = docx.Document()
    d.add_heading("Protocol", 1)
    d.add_paragraph("Check potassium.")
    t = d.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(1, 0).text = "Drug", "Lisinopril"
    buf = io.BytesIO()
    d.save(buf)
    doc = parse_bytes(buf.getvalue(), "p.docx")
    assert doc.blocks[0].kind == "heading" and any("Lisinopril" in b.text for b in doc.blocks)

    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "Big Heading", fontsize=20)
    page.insert_text((72, 110), "Normal body text about sepsis management.", fontsize=10)
    page.insert_text((72, 125), "More body text continues here.", fontsize=10)
    doc = parse_bytes(pdf.tobytes(), "s.pdf")
    assert doc.blocks[0].kind == "heading" and doc.blocks[0].text == "Big Heading"
    assert any("sepsis" in b.text and b.page == 1 for b in doc.blocks)
