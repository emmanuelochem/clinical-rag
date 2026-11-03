import json

from fastapi.testclient import TestClient

from app.agent.orchestrator import extract_citations
from app.main import create_app
from app.store.vectors import build_filter, sanitize_fts


def test_citation_extraction_and_fts_sanitizing():
    assert extract_citations("a [1] b [2, 3] c [9] [1]", 3) == [1, 2, 3]
    assert sanitize_fts('chest "pain" AND (fever) OR x:y') == "chest pain fever x y"


async def test_hybrid_retrieval_scoping(seeded):
    s = seeded
    kb = await s.retriever.search("hyperkalaemia potassium ECG peaked T waves", where=build_filter("kb"), top_k=3)
    assert kb and kb[0].scope == "kb" and "yperkal" in kb[0].doc_title
    assert kb[0].keyword_rank is not None and kb[0].vector_rank is not None  # fused from both retrievers
    pid = s.db.query("SELECT id FROM patients LIMIT 1")[0]["id"]
    notes = await s.retriever.search("blood pressure medications plan", where=build_filter("patient", pid), top_k=5)
    assert notes and all(n.scope == "patient" for n in notes)
    owner = {r["id"] for r in s.db.query("SELECT id FROM notes WHERE patient_id = ?", (pid,))}
    assert all(n.chunk.doc_id in owner for n in notes)  # never leaks other patients' notes


def _events(resp) -> list[dict]:
    return [json.loads(line[6:]) for line in resp.text.splitlines() if line.startswith("data: ")]


async def test_api_end_to_end(seeded):
    s = seeded
    with TestClient(create_app(s)) as c:
        h = c.get("/api/health").json()
        assert h["patients"] == 12 and h["kb_documents"] >= 10
        pts = c.get("/api/patients").json()
        diabetic = next(p for p in pts if any("diabetes" in x.lower() for x in p["conditions"]))
        detail = c.get(f"/api/patients/{diabetic['id']}").json()
        assert detail["patient"]["id"] == diabetic["id"] and "alerts" in detail and detail["available"]
        series = c.get(f"/api/patients/{diabetic['id']}/series", params={"codes": "4548-4,33914-3"}).json()
        assert series[0]["name"] == "HbA1c" and len(series[0]["points"]) >= 2

        r = c.post("/api/chat", json={"message": "How has the HbA1c trended?", "patient_id": diabetic["id"], "mode": "agentic"})
        ev = _events(r)
        types = [e["type"] for e in ev]
        assert types[-1] == "done" and "sources" in types and "chart" in types
        sources = next(e for e in ev if e["type"] == "sources")["sources"]
        assert sources[0]["kind"] == "record" and any(x["kind"] == "kb" for x in sources)
        assert any(x["kind"] == "note" for x in sources)
        assert next(e for e in ev if e["type"] == "chart")["chart"]["code"] == "4548-4"
        assert ev[-1]["citations"] == [1, 2]
        assert s.llm.calls[:2] == ["plan", "reflect"]

        ed = s.db.one("SELECT patient_id FROM notes WHERE type = 'ED triage note' LIMIT 1")
        r = c.post("/api/differential", json={"patient_id": ed["patient_id"], "symptoms": ["chest pain", "diaphoresis"]})
        ev = _events(r)
        result = next(e for e in ev if e["type"] == "result")["result"]
        top = result["differentials"][0]
        assert top["condition"] == "Acute coronary syndrome"
        assert [x["source"] for x in top["supporting"]] == [1, None]  # out-of-range citation nulled
        assert any(e["type"] == "alerts" for e in ev)

        cohort = c.get("/api/cohort").json()
        assert cohort["n_patients"] == 12 and cohort["prevalence"]
        audit = c.get("/api/audit").json()
        assert {"view_record", "assistant_query", "differential"} <= {a["action"] for a in audit}


async def test_upload_and_delete(services):
    with TestClient(create_app(services)) as c:
        md = b"# Gout\n\n## Treatment\n\nAllopurinol lowers urate. Colchicine treats acute flares."
        r = c.post("/api/documents", files=[("files", ("gout.md", md, "text/markdown"))])
        did = r.json()[0]["id"]
        docs = c.get("/api/documents").json()
        assert docs[0]["status"] == "ready" and docs[0]["num_chunks"] >= 1
        hits = c.post("/api/search", json={"query": "colchicine flare", "scope": "kb"}).json()
        assert hits and hits[0]["chunk"]["doc_id"] == did
        assert c.get(f"/api/documents/{did}/file").status_code == 200
        c.delete(f"/api/documents/{did}")
        assert c.post("/api/search", json={"query": "colchicine flare", "scope": "kb"}).json() == []
        assert c.post("/api/documents", files=[("files", ("x.exe", b"MZ", "application/octet-stream"))]).status_code == 415
