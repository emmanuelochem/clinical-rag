"""Agentic RAG orchestration for the clinical assistant.

Agentic mode:  plan (rewrite + decompose) → gather (patient record, trends, notes, reference) →
               reflect (sufficient? else follow-up queries, up to N rounds) → grounded, cited answer.
Fast mode:     heuristic plan → single gather round → answer.

Everything is streamed as typed events so the UI can show the agent's work as it happens.
"""

from __future__ import annotations

import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from app.agent import prompts
from app.clinical import safety
from app.clinical.catalog import ALIASES, BY_NAME, OBS, resolve_obs
from app.clinical.repository import ClinicalRepo
from app.config import Settings
from app.models import ChatRequest, RetrievedChunk
from app.providers.llm import LLM
from app.retrieval.hybrid import HybridRetriever
from app.store.vectors import build_filter

log = logging.getLogger(__name__)

Event = dict[str, Any]
TREND_WORDS = re.compile(r"\b(trend\w*|over time|chart\w*|graph\w*|plot\w*|history of|progress\w*|trajector\w*|chang\w*|control\w*)\b", re.I)


class SourceBook:
    """Accumulates numbered sources across retrieval rounds (deduplicated)."""

    def __init__(self) -> None:
        self.items: list[dict] = []
        self._keys: set[str] = set()

    def add_record(self, key: str, title: str, text: str, *, patient_id: str, chart_code: str | None = None) -> int | None:
        if key in self._keys or not text:
            return None
        self._keys.add(key)
        self.items.append({"n": len(self.items) + 1, "kind": "record", "title": title, "text": text,
                           "patient_id": patient_id, "chart_code": chart_code, "key": key})
        return len(self.items)

    def add_chunk(self, r: RetrievedChunk) -> int | None:
        if r.chunk.id in self._keys:
            return None
        self._keys.add(r.chunk.id)
        self.items.append({
            "n": len(self.items) + 1, "kind": "note" if r.scope == "patient" else "kb", "title": r.doc_title,
            "text": r.chunk.text, "source": r.source, "date": r.date, "doc_id": r.chunk.doc_id, "chunk_id": r.chunk.id,
            "headings": r.chunk.headings, "page": r.chunk.page_start, "score": r.score, "rerank_score": r.rerank_score,
            "vector_rank": r.vector_rank, "keyword_rank": r.keyword_rank, "matched_queries": r.matched_queries,
            "context_before": r.context_before, "context_after": r.context_after, "key": r.chunk.id,
        })
        return len(self.items)

    def prompt_block(self, max_chars: int = 1600) -> str:
        out = []
        for s in self.items:
            label = {"record": "Patient record", "note": f"Clinical note ({s.get('date', '')})", "kb": "Medical reference"}[s["kind"]]
            crumb = " > ".join(s.get("headings") or [])
            out.append(f"[{s['n']}] {label} — {s['title']}{' > ' + crumb if crumb else ''}\n{s['text'][:max_chars]}")
        return "\n\n".join(out)

    def public(self) -> list[dict]:
        return [{k: v for k, v in s.items() if k != "key"} for s in self.items]


# Some models (e.g. gpt-oss) emit their native citation style "【3†L1-L4】" instead of "[3]".
NATIVE_CITE = re.compile(r"【(\d+)(?:†[^】]*)?】")


def normalize_citations(text: str) -> str:
    return NATIVE_CITE.sub(r"[\1]", text)


def extract_citations(text: str, n_sources: int) -> list[int]:
    text = normalize_citations(text)
    nums = []
    for m in re.finditer(r"\[(\d+(?:\s*,\s*\d+)*)\]", text):
        for x in m.group(1).split(","):
            v = int(x)
            if 1 <= v <= n_sources and v not in nums:
                nums.append(v)
    return nums


def heuristic_lab_terms(text: str) -> list[str]:
    t = text.lower()
    found = []
    for term in sorted(set(ALIASES) | set(BY_NAME), key=len, reverse=True):
        if len(term) <= 2:
            if re.search(rf"\b{re.escape(term)}\b", t) and term in ("bp", "hr", "k"):
                found.append(term)
        elif re.search(rf"\b{re.escape(term)}\b", t):
            found.append(term)
    codes, out = set(), []
    for f in found:
        o = resolve_obs(f)
        if o and o.code not in codes:
            codes.add(o.code)
            out.append(o.name)
    return out


class ClinicalAgent:
    def __init__(self, settings: Settings, llm: LLM, retriever: HybridRetriever, repo: ClinicalRepo):
        self.s, self.llm, self.retriever, self.repo = settings, llm, retriever, repo

    # ------------------------------------------------------------------ planning

    async def _plan(self, req: ChatRequest) -> dict:
        q = req.message
        pid = req.patient_id
        fallback = {
            "standalone_question": q,
            "note_queries": [q] if pid else [],
            "kb_queries": [q],
            "lab_tests": heuristic_lab_terms(q) if pid else [],
            "chart": bool(pid and TREND_WORDS.search(q)),
        }
        if req.mode == "fast":
            return fallback
        history = "\n".join(f"{m.role}: {m.content[:500]}" for m in req.history[-6:]) or "(none)"
        p = self.repo.patient(pid) if pid else None
        available = ", ".join(c["name"] for c in self.repo.available_codes(pid)) if pid else "n/a"
        patient_line = f"Selected patient: {p['first_name']} {p['last_name']}, {p['age']} y {p['sex']}." if p else "No patient selected."
        try:
            plan = await self.llm.complete_json([{"role": "user", "content": prompts.PLANNER.format(
                max_q=self.s.max_subqueries, patient_line=patient_line, available=available, history=history, question=q)}],
                model=self.s.planner)
            if not isinstance(plan, dict):
                raise ValueError("planner returned non-object")
        except Exception as e:
            log.warning("Planner failed (%s); using heuristic plan", e)
            return fallback
        out = {
            "standalone_question": str(plan.get("standalone_question") or q),
            "note_queries": [str(x) for x in plan.get("note_queries") or []][: self.s.max_subqueries] if pid else [],
            "kb_queries": [str(x) for x in plan.get("kb_queries") or []][: self.s.max_subqueries],
            "lab_tests": [str(x) for x in plan.get("lab_tests") or []][:6] if pid else [],
            "chart": bool(plan.get("chart")) or bool(pid and TREND_WORDS.search(q)),
        }
        # Always include the literal question so decomposition never loses recall.
        if pid and out["standalone_question"] not in out["note_queries"]:
            out["note_queries"].insert(0, out["standalone_question"])
        if out["standalone_question"] not in out["kb_queries"]:
            out["kb_queries"].insert(0, out["standalone_question"])
        out["lab_tests"] = list(dict.fromkeys(out["lab_tests"] + fallback["lab_tests"]))
        return out

    # ------------------------------------------------------------------ gathering

    async def _gather(self, book: SourceBook, pid: str | None, plan: dict, question: str,
                      doc_ids: list[str] | None, top_k: int | None) -> AsyncIterator[Event]:
        if pid and plan.get("note_queries"):
            yield {"type": "status", "step": "notes", "message": f"Searching clinical notes ({len(plan['note_queries'])} queries)"}
            res = await self.retriever.search(plan["note_queries"], where=build_filter("patient", pid),
                                              top_k=max(3, (top_k or self.s.final_top_k) // 2 + 1), rerank_query=question)
            for r in res:
                book.add_chunk(r)
        if plan.get("kb_queries"):
            yield {"type": "status", "step": "kb", "message": f"Searching medical reference ({len(plan['kb_queries'])} queries)"}
            res = await self.retriever.search(plan["kb_queries"], where=build_filter("kb", doc_ids=doc_ids),
                                              top_k=top_k or self.s.final_top_k, rerank_query=question)
            for r in res:
                book.add_chunk(r)

    def _record_sources(self, book: SourceBook, pid: str, plan: dict) -> list[dict]:
        p = self.repo.patient(pid)
        name = f"{p['first_name']} {p['last_name']}"
        book.add_record(f"summary:{pid}", f"Patient summary — {name}", self.repo.summary_text(pid), patient_id=pid)
        charts = []
        for term in plan.get("lab_tests", []):
            o = resolve_obs(term)
            if not o:
                continue
            txt = self.repo.trend_text(pid, o.code)
            if txt and book.add_record(f"trend:{pid}:{o.code}", f"{o.name} results — {name}", txt, patient_id=pid, chart_code=o.code):
                if plan.get("chart"):
                    series = self.repo.series(pid, o.code)
                    if series and len(series["points"]) >= 2:
                        charts.append(series)
                        if o.code == "8480-6" and (dia := self.repo.series(pid, "8462-4")):
                            series["companion"] = dia
        return charts

    # ------------------------------------------------------------------ main loop

    async def run(self, req: ChatRequest) -> AsyncIterator[Event]:
        pid = req.patient_id
        book = SourceBook()
        alerts: list[dict] = []

        if pid:
            p = self.repo.patient(pid)
            if not p:
                yield {"type": "error", "message": "Patient not found"}
                return
            enc, last_obs = self.repo.latest_encounter_obs(pid)
            alerts = safety.evaluate(latest_obs=self.repo.latest(pid), medications=self.repo.medications(pid, True),
                                     conditions=self.repo.conditions(pid), presentation=req.message + " " + (enc or {}).get("reason", ""))["alerts"]
            if alerts:
                yield {"type": "alerts", "alerts": alerts}

        yield {"type": "status", "step": "plan", "message": "Planning retrieval" if req.mode == "agentic" else "Fast retrieval"}
        plan = await self._plan(req)
        yield {"type": "plan", "plan": plan}
        question = plan["standalone_question"]

        if pid:
            yield {"type": "status", "step": "record", "message": "Reading structured patient record"}
            for chart in self._record_sources(book, pid, plan):
                yield {"type": "chart", "chart": chart}

        async for ev in self._gather(book, pid, plan, question, req.doc_ids, req.top_k):
            yield ev

        if req.mode == "agentic":
            seen_queries = set(plan["kb_queries"]) | set(plan["note_queries"])
            for rnd in range(1, self.s.max_agent_rounds):
                yield {"type": "status", "step": "reflect", "message": f"Checking evidence sufficiency (round {rnd})"}
                evidence = "\n".join(f"[{s['n']}] {s['title']}: {s['text'][:240]}" for s in book.items) or "(no evidence)"
                try:
                    verdict = await self.llm.complete_json([{"role": "user", "content": prompts.REFLECT.format(
                        question=question, evidence=evidence)}], model=self.s.planner)
                except Exception as e:
                    log.warning("Reflection failed: %s", e)
                    break
                if not isinstance(verdict, dict) or verdict.get("sufficient", True):
                    break
                follow = [q for q in (verdict.get("followup_queries") or []) if isinstance(q, str) and q not in seen_queries]
                follow = follow[: self.s.max_subqueries]
                if not follow:
                    break
                seen_queries |= set(follow)
                yield {"type": "plan", "plan": {"followup_queries": follow, "missing": verdict.get("missing", "")}}
                before = len(book.items)
                async for ev in self._gather(book, pid, {"note_queries": follow if pid else [], "kb_queries": follow},
                                             question, req.doc_ids, req.top_k):
                    yield ev
                if len(book.items) == before:
                    break

        yield {"type": "sources", "sources": book.public()}
        if not book.items:
            yield {"type": "token", "text": "I couldn't find any relevant information in the patient record or knowledge base for this question."}
            yield {"type": "done", "citations": []}
            return

        yield {"type": "status", "step": "answer", "message": "Writing answer"}
        alert_txt = ""
        if alerts:
            alert_txt = "\nActive safety alerts for this patient (mention if relevant): " + "; ".join(
                f"{a['severity'].upper()}: {a['title']}" for a in alerts[:6])
        messages = [{"role": "system", "content": prompts.SYSTEM_ASSISTANT.format(alerts=alert_txt)}]
        for m in req.history[-6:]:
            messages.append({"role": m.role, "content": m.content})
        messages.append({"role": "user", "content": f"Sources:\n\n{book.prompt_block()}\n\n---\nQuestion: {question}"})

        answer = ""
        async for piece in self.llm.stream(messages):
            answer += piece
            yield {"type": "token", "text": piece}
        yield {"type": "done", "citations": extract_citations(answer, len(book.items))}


__all__ = ["ClinicalAgent", "SourceBook", "extract_citations", "OBS"]
