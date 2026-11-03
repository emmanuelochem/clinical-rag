"""FastAPI application."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from fastapi import BackgroundTasks, FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

from app.clinical import safety
from app.config import get_settings
from app.ingest.parsers import SUPPORTED_EXTENSIONS
from app.ingest.pipeline import doc_id_for
from app.models import ChatRequest, DifferentialRequest, SearchRequest, UrlIngestRequest
from app.services import Services, build_services
from app.store.vectors import build_filter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("app")


def create_app(services: Services | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.svc = services or build_services(get_settings())
        yield

    app = FastAPI(title="Clinical RAG", version="1.0.0", lifespan=lifespan)
    settings = services.settings if services else get_settings()
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins, allow_methods=["*"], allow_headers=["*"])

    def svc(request: Request) -> Services:
        return request.app.state.svc

    async def sse(events: AsyncIterator[dict]) -> AsyncIterator[bytes]:
        try:
            async for ev in events:
                yield f"data: {json.dumps(ev, default=str)}\n\n".encode()
        except (httpx.ConnectError, httpx.ConnectTimeout):
            yield _sse_err("Cannot reach Ollama. Is it running? (ollama serve)")
        except Exception as e:
            log.exception("stream failed")
            yield _sse_err(str(e))

    def _sse_err(msg: str) -> bytes:
        return f"data: {json.dumps({'type': 'error', 'message': msg})}\n\n".encode()

    def stream(events: AsyncIterator[dict]) -> StreamingResponse:
        return StreamingResponse(sse(events), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    # ------------------------------------------------------------------ health

    @app.get("/api/health")
    async def health(request: Request):
        s = svc(request)
        ollama: dict = {"reachable": False}
        try:
            async with httpx.AsyncClient(timeout=3) as c:
                r = await c.get(f"{s.settings.ollama_url}/api/tags")
                names = [m["name"] for m in r.json().get("models", [])]
            need = {s.settings.chat_model, s.settings.planner, s.settings.embed_model}
            have = lambda m: any(n == m or n.split(":")[0] == m or n == f"{m}:latest" for n in names)  # noqa: E731
            ollama = {"reachable": True, "models": names, "missing": sorted(m for m in need if not have(m))}
        except Exception:
            pass
        return {
            "status": "ok", "ollama": ollama, "reranker": s.reranker.name,
            "chat_model": s.settings.chat_model, "embed_model": s.settings.embed_model,
            "patients": s.db.one("SELECT COUNT(*) n FROM patients")["n"],
            "kb_documents": s.db.one("SELECT COUNT(*) n FROM documents WHERE scope='kb' AND status='ready'")["n"],
        }

    # ------------------------------------------------------------------ patients

    @app.get("/api/patients")
    async def patients(request: Request, q: str = ""):
        return svc(request).repo.list_patients(q)

    @app.get("/api/patients/{pid}")
    async def patient(request: Request, pid: str):
        s = svc(request)
        summary = s.repo.summary(pid)
        if not summary:
            raise HTTPException(404, "Patient not found")
        s.db.audit("view_record", pid)
        enc = summary["last_encounter"] or {}
        screen = safety.evaluate(latest_obs=s.repo.latest(pid), medications=s.repo.medications(pid, True),
                                 conditions=summary["conditions"], presentation=enc.get("reason", ""))
        return {**summary, **screen, "available": s.repo.available_codes(pid)}

    @app.get("/api/patients/{pid}/series")
    async def series(request: Request, pid: str, codes: str):
        s = svc(request)
        out = [x for c in codes.split(",") if (x := s.repo.series(pid, c.strip()))]
        return out

    @app.get("/api/patients/{pid}/notes")
    async def notes(request: Request, pid: str):
        return svc(request).repo.notes(pid)

    @app.get("/api/notes/{note_id}")
    async def note(request: Request, note_id: str):
        s = svc(request)
        n = s.repo.note(note_id)
        if not n:
            raise HTTPException(404)
        s.db.audit("view_note", n["patient_id"], note_id)
        return n

    @app.get("/api/cohort")
    async def cohort(request: Request):
        return svc(request).repo.cohort()

    # ------------------------------------------------------------------ assistant

    @app.post("/api/chat")
    async def chat(request: Request, req: ChatRequest):
        s = svc(request)
        if not req.message.strip():
            raise HTTPException(400, "Empty message")
        s.db.audit("assistant_query", req.patient_id, req.message)
        return stream(s.agent.run(req))

    @app.post("/api/differential")
    async def differential(request: Request, req: DifferentialRequest):
        s = svc(request)
        if not req.symptoms and not req.notes.strip():
            raise HTTPException(400, "Provide at least one symptom")
        s.db.audit("differential", req.patient_id, ", ".join(req.symptoms) + " | " + req.notes)
        return stream(s.differential.run(req))

    @app.post("/api/search")
    async def search(request: Request, req: SearchRequest):
        s = svc(request)
        res = await s.retriever.search(req.query, where=build_filter(req.scope, req.patient_id, req.doc_ids),
                                       top_k=req.top_k, rerank=req.rerank)
        return [r.model_dump() for r in res]

    # ------------------------------------------------------------------ knowledge base

    @app.get("/api/documents")
    async def documents(request: Request, scope: str = "kb"):
        rows = svc(request).db.query("SELECT * FROM documents WHERE scope = ? ORDER BY created_at DESC", (scope,))
        for r in rows:
            r["has_file"] = bool(r.pop("file_path", None))
        return rows

    @app.post("/api/documents")
    async def upload(request: Request, bg: BackgroundTasks, files: list[UploadFile] = File(...)):
        s = svc(request)
        out = []
        for f in files:
            name = Path(f.filename or "upload").name
            if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS:
                raise HTTPException(415, f"Unsupported file type: {name}")
            data = await f.read()
            if len(data) > s.settings.max_upload_mb * 1024 * 1024:
                raise HTTPException(413, f"{name} exceeds {s.settings.max_upload_mb} MB")
            did = doc_id_for(data, name)
            path = s.settings.uploads_dir / f"{did}{Path(name).suffix.lower()}"
            path.write_bytes(data)
            s.ingestor.register(did, title=Path(name).stem, source=name, mime=f.content_type or "", size=len(data), file_path=str(path))
            bg.add_task(s.ingestor.ingest_file, did, data, name)
            out.append({"id": did, "source": name, "status": "pending"})
        return out

    @app.post("/api/documents/url")
    async def upload_url(request: Request, bg: BackgroundTasks, req: UrlIngestRequest):
        s = svc(request)
        did = doc_id_for(req.url.encode(), "url")
        s.ingestor.register(did, title=req.url, source=req.url, mime="text/html", size=0)
        bg.add_task(s.ingestor.ingest_url, did, req.url)
        return {"id": did, "source": req.url, "status": "pending"}

    @app.delete("/api/documents/{doc_id}")
    async def delete_doc(request: Request, doc_id: str):
        s = svc(request)
        await asyncio.to_thread(s.ingestor.delete, doc_id)
        return {"deleted": doc_id}

    @app.get("/api/documents/{doc_id}/file")
    async def doc_file(request: Request, doc_id: str):
        row = svc(request).db.one("SELECT file_path, source FROM documents WHERE id = ?", (doc_id,))
        if not row or not row["file_path"] or not Path(row["file_path"]).exists():
            raise HTTPException(404, "No stored file for this document")
        return FileResponse(row["file_path"], filename=row["source"], content_disposition_type="inline")

    @app.get("/api/documents/{doc_id}/chunks")
    async def doc_chunks(request: Request, doc_id: str):
        return await asyncio.to_thread(svc(request).store.doc_chunks, doc_id)

    # ------------------------------------------------------------------ admin

    @app.post("/api/admin/seed")
    async def admin_seed(request: Request, patients: int = 30, reset: bool = False):
        from app.seed import seed

        return await seed(svc(request), patients=patients, reset=reset)

    @app.get("/api/audit")
    async def audit(request: Request, limit: int = 200):
        return svc(request).db.query("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))

    return app


app = create_app()
