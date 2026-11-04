"""Evidence-cited differential diagnosis (clinical decision support).

1. Deterministic safety screen (critical values, NEWS2, red flags, med-lab checks)
2. Evidence gathering: patient summary + relevant lab trends, the patient's own notes,
   and medical reference passages for the presenting symptoms (hybrid search + rerank)
3. LLM synthesis into a structured, ranked differential where every supporting finding
   must cite a numbered source; citations are validated server-side.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from app.agent import prompts
from app.agent.orchestrator import SourceBook, heuristic_lab_terms
from app.clinical import safety
from app.clinical.catalog import OBS
from app.clinical.repository import ClinicalRepo
from app.config import Settings
from app.models import DifferentialRequest
from app.providers.llm import LLM
from app.retrieval.hybrid import HybridRetriever
from app.store.vectors import build_filter

log = logging.getLogger(__name__)

LIKELIHOOD_ORDER = {"high": 0, "moderate": 1, "low": 2}
DISCLAIMER = ("Decision support only. Generated from a synthetic record and reference sources by a language model; "
              "it may be incomplete or wrong. Verify against the full clinical picture and current guidelines.")


def _validate(result: dict, n_sources: int) -> dict:
    def ok(n) -> int | None:
        try:
            n = int(n)
        except (TypeError, ValueError):
            return None
        return n if 1 <= n <= n_sources else None

    diffs = []
    for d in result.get("differentials") or []:
        if not isinstance(d, dict) or not d.get("condition"):
            continue
        lk = str(d.get("likelihood", "low")).lower()
        lk = lk if lk in LIKELIHOOD_ORDER else "moderate" if "mod" in lk else "low"
        sup = [{"finding": str(s.get("finding", "")), "source": ok(s.get("source"))}
               for s in d.get("supporting") or [] if isinstance(s, dict) and s.get("finding")]
        ag = [{"finding": str(s.get("finding", "")), "source": ok(s.get("source"))}
              for s in d.get("against") or [] if isinstance(s, dict) and s.get("finding")]
        diffs.append({
            "condition": str(d["condition"]), "icd10": str(d.get("icd10") or ""), "likelihood": lk,
            "cant_miss": bool(d.get("cant_miss")), "reasoning": str(d.get("reasoning") or ""),
            "supporting": sup, "against": ag,
            "next_steps": [str(x) for x in d.get("next_steps") or []][:6],
            "evidence_strength": sum(1 for s in sup if s["source"]),
        })
    diffs.sort(key=lambda d: (LIKELIHOOD_ORDER[d["likelihood"]], not d["cant_miss"], -d["evidence_strength"]))
    workup = [str(x) for x in result.get("recommended_workup") or [] if str(x).strip()][:10]
    if not workup:  # models sometimes omit it: derive from the leading and can't-miss diagnoses
        for d in [x for x in diffs if x["likelihood"] == "high" or x["cant_miss"]][:4] or diffs[:2]:
            for step in d["next_steps"][:2]:
                if step.lower() not in {w.lower() for w in workup}:
                    workup.append(step)
    return {
        "summary": str(result.get("summary") or ""),
        "differentials": diffs[:8],
        "recommended_workup": workup[:10],
        "information_gaps": [str(x) for x in result.get("information_gaps") or []][:8],
    }


class DifferentialEngine:
    def __init__(self, settings: Settings, llm: LLM, retriever: HybridRetriever, repo: ClinicalRepo):
        self.s, self.llm, self.retriever, self.repo = settings, llm, retriever, repo

    async def run(self, req: DifferentialRequest) -> AsyncIterator[dict]:
        pid = req.patient_id
        p = self.repo.patient(pid)
        if not p:
            yield {"type": "error", "message": "Patient not found"}
            return
        symptoms = [s.strip() for s in req.symptoms if s.strip()]
        presentation = f"{p['age']}-year-old {p['sex']} with " + (", ".join(symptoms) or "unspecified symptoms")
        if req.notes.strip():
            presentation += f". Details: {req.notes.strip()}"

        yield {"type": "status", "step": "safety", "message": "Running deterministic safety screen"}
        screen = safety.evaluate(latest_obs=self.repo.latest(pid), medications=self.repo.medications(pid, True),
                                 conditions=self.repo.conditions(pid), presentation=presentation)
        yield {"type": "alerts", "alerts": screen["alerts"], "news2": screen["news2"]}

        yield {"type": "status", "step": "record", "message": "Reading patient record and lab trends"}
        book = SourceBook()
        name = f"{p['first_name']} {p['last_name']}"
        book.add_record(f"summary:{pid}", f"Patient summary — {name}", self.repo.summary_text(pid), patient_id=pid)
        enc, last_obs = self.repo.latest_encounter_obs(pid)
        if enc and last_obs:
            txt = f"{enc['date']} {enc['type']} ({enc['reason']}): " + "; ".join(
                f"{o['name']} {o['value']} {o['unit']}{'' if o['interpretation'] == 'N' else ' [' + o['interpretation'] + ']'}" for o in last_obs)
            book.add_record(f"enc:{enc['id']}", f"Most recent encounter results — {enc['date']}", txt, patient_id=pid)
        # Trends for abnormal labs plus labs mentioned in the presentation.
        codes = {o["code"] for o in self.repo.latest(pid, "lab") if o["interpretation"] != "N"}
        codes |= {c for t in heuristic_lab_terms(presentation) for c in OBS if OBS[c].name == t}
        for code in sorted(codes)[:8]:
            book.add_record(f"trend:{pid}:{code}", f"{OBS[code].name} results — {name}", self.repo.trend_text(pid, code),
                            patient_id=pid, chart_code=code)

        yield {"type": "status", "step": "notes", "message": "Searching the patient's clinical notes"}
        note_q = [presentation] + symptoms[:3]
        for r in await self.retriever.search(note_q, where=build_filter("patient", pid), top_k=4, rerank_query=presentation):
            book.add_chunk(r)

        yield {"type": "status", "step": "kb", "message": "Searching medical reference for these symptoms"}
        conds = [c["display"] for c in self.repo.conditions(pid) if c["status"] == "active"]
        kb_q = [f"differential diagnosis {' '.join(symptoms)}", *[f"{s} causes evaluation red flags" for s in symptoms[:3]]]
        if conds:
            kb_q.append(f"{' '.join(symptoms[:2])} in patient with {conds[0]}")
        for r in await self.retriever.search(kb_q, where=build_filter("kb"), top_k=self.s.final_top_k, rerank_query=presentation):
            book.add_chunk(r)

        yield {"type": "sources", "sources": book.public()}
        yield {"type": "status", "step": "synthesize", "message": "Synthesising differential diagnosis"}
        alerts_txt = "; ".join(f"{a['severity']}: {a['title']}" for a in screen["alerts"]) or "none"
        prompt = prompts.DIFFERENTIAL.format(presentation=presentation, alerts=alerts_txt, sources=book.prompt_block(1200))
        try:
            raw = await self.llm.complete_json([{"role": "user", "content": prompt}])
            result = _validate(raw if isinstance(raw, dict) else {}, len(book.items))
        except Exception as e:
            log.exception("Differential synthesis failed")
            yield {"type": "error", "message": f"Model failed to produce a structured differential: {e}"}
            return
        if not result["differentials"]:
            yield {"type": "error", "message": "The model returned no usable differentials. Try a larger model or add more detail."}
            return
        yield {"type": "result", "result": {**result, "presentation": presentation, "disclaimer": DISCLAIMER}}
        yield {"type": "done"}
