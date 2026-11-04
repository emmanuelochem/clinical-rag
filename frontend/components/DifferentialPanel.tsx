"use client";

import { useEffect, useState } from "react";
import { AlertOctagon, Check, ClipboardCheck, HelpCircle, Minus, Plus, Search, X } from "lucide-react";
import { streamEvents } from "@/lib/api";
import type { Alert, DifferentialResult, News2, Source } from "@/lib/types";
import { CitationChip } from "./CitedMarkdown";
import { SourceDrawer } from "./SourceDrawer";
import { AlertsBanner, Spinner } from "./ui";

const COMMON = ["chest pain", "shortness of breath", "fatigue", "fever", "cough", "dizziness", "palpitations", "leg swelling",
  "abdominal pain", "nausea", "headache", "weakness", "polyuria", "black stools", "diaphoresis", "confusion"];

const LIKELIHOOD = {
  high: { label: "High", cls: "bg-critical-soft text-critical", bar: "bg-critical", w: "w-full" },
  moderate: { label: "Moderate", cls: "bg-warning-soft text-warning", bar: "bg-warning", w: "w-2/3" },
  low: { label: "Low", cls: "bg-panel-2 text-muted", bar: "bg-muted", w: "w-1/3" },
};

export function DifferentialPanel({ patientId, initialSymptoms = [], initialNotes = "" }: {
  patientId: string; initialSymptoms?: string[]; initialNotes?: string;
}) {
  const [symptoms, setSymptoms] = useState<string[]>(initialSymptoms);
  const [draft, setDraft] = useState("");
  const [notes, setNotes] = useState(initialNotes);
  const [steps, setSteps] = useState<string[]>([]);
  const [alerts, setAlerts] = useState<Alert[]>([]);
  const [news2, setNews2] = useState<News2 | null>(null);
  const [sources, setSources] = useState<Source[]>([]);
  const [result, setResult] = useState<DifferentialResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [running, setRunning] = useState(false);
  const [open, setOpen] = useState<Source | null>(null);

  useEffect(() => { setSymptoms(initialSymptoms); setNotes(initialNotes); setResult(null); setSources([]); setAlerts([]); setSteps([]); },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [patientId]);

  const add = (s: string) => { const v = s.trim().toLowerCase(); if (v && !symptoms.includes(v)) setSymptoms([...symptoms, v]); setDraft(""); };
  const openSrc = (n: number) => setOpen(sources.find((s) => s.n === n) ?? null);

  async function run() {
    setRunning(true); setSteps([]); setResult(null); setError(null); setSources([]);
    try {
      for await (const ev of streamEvents("/api/differential", { patient_id: patientId, symptoms, notes })) {
        if (ev.type === "status") setSteps((s) => [...s, ev.message]);
        else if (ev.type === "alerts") { setAlerts(ev.alerts); setNews2(ev.news2 ?? null); }
        else if (ev.type === "sources") setSources(ev.sources);
        else if (ev.type === "result") setResult(ev.result);
        else if (ev.type === "error") setError(ev.message);
      }
    } catch (e) { setError(String(e)); } finally { setRunning(false); }
  }

  return (
    <div className="space-y-4">
      <div className="card p-4">
        <div className="label mb-2">Presenting symptoms</div>
        <div className="flex flex-wrap items-center gap-1.5">
          {symptoms.map((s) => (
            <span key={s} className="inline-flex items-center gap-1 rounded-full bg-accent-soft px-2.5 py-1 text-[13px] font-medium text-accent">
              {s}<button onClick={() => setSymptoms(symptoms.filter((x) => x !== s))} aria-label={`Remove ${s}`}><X size={12} /></button>
            </span>
          ))}
          <input value={draft} onChange={(e) => setDraft(e.target.value)} placeholder="Type a symptom and press Enter"
            onKeyDown={(e) => { if (e.key === "Enter" || e.key === ",") { e.preventDefault(); add(draft); } }}
            className="min-w-[200px] flex-1 bg-transparent px-1 py-1 text-sm outline-none" />
        </div>
        <div className="mt-2 flex flex-wrap gap-1">
          {COMMON.filter((c) => !symptoms.includes(c)).slice(0, 12).map((c) => (
            <button key={c} onClick={() => add(c)} className="rounded-full border border-line px-2 py-0.5 text-xs text-muted hover:border-accent hover:text-accent">+ {c}</button>
          ))}
        </div>
        <textarea value={notes} onChange={(e) => setNotes(e.target.value)} rows={2} className="input mt-3"
          placeholder="Onset, duration, severity, exam findings, relevant negatives…" />
        <div className="mt-3 flex items-center gap-3">
          <button className="btn-primary" disabled={running || (!symptoms.length && !notes.trim())} onClick={run}>
            {running ? <Spinner /> : <Search size={14} />} Generate differential
          </button>
          {running && <span className="text-xs text-muted">{steps.at(-1)}</span>}
        </div>
      </div>

      {(alerts.length > 0 || news2) && (
        <div className="space-y-2">
          {news2 && (
            <div className="flex flex-wrap items-center gap-2 text-sm">
              <span className="label">NEWS2</span>
              <span className={`rounded-md px-2 py-0.5 font-bold ${news2.risk === "high" ? "bg-critical text-white" : news2.risk === "low" ? "bg-ok-soft text-ok" : "bg-warning-soft text-warning"}`}>
                {news2.score} · {news2.risk}
              </span>
              <span className="text-xs text-muted">{Object.entries(news2.components).filter(([, v]) => v).map(([k, v]) => `${k} +${v}`).join(" · ")}</span>
            </div>
          )}
          <AlertsBanner alerts={alerts} />
        </div>
      )}

      {error && <div className="rounded-lg border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical">{error}</div>}

      {result && (
        <div className="space-y-4">
          <div className="card p-4">
            <div className="label mb-1">Clinical synthesis</div>
            <p className="text-[14.5px] leading-relaxed">{result.summary}</p>
          </div>
          <div className="space-y-3">
            {result.differentials.map((d, i) => {
              const L = LIKELIHOOD[d.likelihood];
              return (
                <div key={i} className={`card p-4 ${d.cant_miss ? "border-l-4 border-l-critical" : ""}`}>
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-sm font-semibold text-muted">{i + 1}.</span>
                    <h3 className="text-[15px] font-semibold">{d.condition}</h3>
                    {d.icd10 && <span className="rounded bg-panel-2 px-1.5 py-0.5 font-mono text-[11px] text-muted">{d.icd10}</span>}
                    <span className={`rounded-md px-2 py-0.5 text-xs font-semibold ${L.cls}`}>{L.label} likelihood</span>
                    {d.cant_miss && <span className="flex items-center gap-1 rounded-md bg-critical px-2 py-0.5 text-xs font-semibold text-white"><AlertOctagon size={12} />Can&apos;t miss</span>}
                    <span className="ml-auto text-xs text-muted">{d.evidence_strength} cited finding{d.evidence_strength === 1 ? "" : "s"}</span>
                  </div>
                  <div className="mt-2 h-1 w-full rounded bg-panel-2"><div className={`h-1 rounded ${L.bar} ${L.w}`} /></div>
                  {d.reasoning && <p className="mt-2.5 text-sm leading-relaxed">{d.reasoning}</p>}
                  <div className="mt-3 grid gap-3 md:grid-cols-3">
                    <FindingList title="Supporting" icon={<Plus size={13} className="text-ok" />} items={d.supporting} sources={sources} onOpen={openSrc} />
                    <FindingList title="Against" icon={<Minus size={13} className="text-critical" />} items={d.against} sources={sources} onOpen={openSrc} />
                    <div>
                      <div className="label mb-1 flex items-center gap-1"><ClipboardCheck size={13} />Next steps</div>
                      <ul className="space-y-1 text-[13px]">{d.next_steps.map((s, j) => <li key={j} className="flex gap-1.5"><Check size={13} className="mt-0.5 shrink-0 text-accent" />{s}</li>)}</ul>
                    </div>
                  </div>
                </div>
              );
            })}
          </div>
          {(result.recommended_workup.length > 0 || result.information_gaps.length > 0) && (
            <div className="grid gap-3 md:grid-cols-2">
              {result.recommended_workup.length > 0 && (
                <div className="card p-4">
                  <div className="label mb-2">Recommended workup</div>
                  <ol className="list-decimal space-y-1 pl-5 text-sm">{result.recommended_workup.map((w, i) => <li key={i}>{w}</li>)}</ol>
                </div>
              )}
              {result.information_gaps.length > 0 && (
                <div className="card p-4">
                  <div className="label mb-2 flex items-center gap-1"><HelpCircle size={13} />Information that would change the differential</div>
                  <ul className="list-disc space-y-1 pl-5 text-sm">{result.information_gaps.map((w, i) => <li key={i}>{w}</li>)}</ul>
                </div>
              )}
            </div>
          )}
          <div>
            <div className="label mb-1.5">Evidence sources ({sources.length})</div>
            <div className="flex flex-wrap gap-1.5">
              {sources.map((s) => (
                <button key={s.n} onClick={() => setOpen(s)} className="flex max-w-xs items-center gap-1.5 rounded-lg border border-line bg-panel px-2 py-1 text-left text-xs hover:border-accent">
                  <span className="font-bold">{s.n}</span><span className="truncate">{s.title}</span>
                </button>
              ))}
            </div>
          </div>
          <p className="rounded-lg bg-panel-2 px-3 py-2 text-xs text-muted">{result.disclaimer}</p>
        </div>
      )}
      <SourceDrawer source={open} onClose={() => setOpen(null)} />
    </div>
  );
}

function FindingList({ title, icon, items, sources, onOpen }: {
  title: string; icon: React.ReactNode; items: { finding: string; source: number | null }[]; sources: Source[]; onOpen: (n: number) => void;
}) {
  return (
    <div>
      <div className="label mb-1 flex items-center gap-1">{icon}{title}</div>
      {items.length === 0 ? <div className="text-[13px] text-muted">None identified</div> : (
        <ul className="space-y-1 text-[13px]">
          {items.map((f, j) => (
            <li key={j}>{f.finding}{f.source != null && <CitationChip n={f.source} source={sources.find((s) => s.n === f.source)} onOpen={onOpen} />}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
