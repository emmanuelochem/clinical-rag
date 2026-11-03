"use client";

import { useEffect, useRef, useState } from "react";
import { ArrowUp, BookOpen, Check, ChevronDown, ChevronRight, ClipboardList, FileText, Square, Sparkles, Zap } from "lucide-react";
import { streamEvents } from "@/lib/api";
import type { Alert, Plan, Series, Source } from "@/lib/types";
import { CitedMarkdown } from "./CitedMarkdown";
import { SourceDrawer } from "./SourceDrawer";
import { TrendChart } from "./TrendChart";
import { AlertsBanner, Spinner } from "./ui";

interface Turn {
  role: "user" | "assistant";
  content: string;
  sources: Source[];
  charts: Series[];
  alerts: Alert[];
  steps: { step: string; message: string }[];
  plans: Plan[];
  citations: number[];
  error?: string;
  streaming?: boolean;
}

const newTurn = (role: Turn["role"], content = ""): Turn =>
  ({ role, content, sources: [], charts: [], alerts: [], steps: [], plans: [], citations: [] });

const SRC_ICON = { record: ClipboardList, note: FileText, kb: BookOpen };

export function Chat({ patientId, suggestions, placeholder, compact = false }: {
  patientId?: string; suggestions: string[]; placeholder?: string; compact?: boolean;
}) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [input, setInput] = useState("");
  const [mode, setMode] = useState<"agentic" | "fast">("agentic");
  const [open, setOpen] = useState<Source | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const endRef = useRef<HTMLDivElement>(null);
  const busy = turns.at(-1)?.streaming ?? false;

  useEffect(() => { setTurns([]); }, [patientId]);
  useEffect(() => { endRef.current?.scrollIntoView({ block: "end" }); }, [turns]);

  const update = (fn: (t: Turn) => void) =>
    setTurns((ts) => {
      const copy = [...ts];
      const last = { ...copy[copy.length - 1] };
      fn(last);
      copy[copy.length - 1] = last;
      return copy;
    });

  async function send(text: string) {
    const msg = text.trim();
    if (!msg || busy) return;
    const history = turns.filter((t) => !t.error).map((t) => ({ role: t.role, content: t.content }));
    setTurns((ts) => [...ts, newTurn("user", msg), { ...newTurn("assistant"), streaming: true }]);
    setInput("");
    const ac = new AbortController();
    abortRef.current = ac;
    try {
      for await (const ev of streamEvents("/api/chat", { message: msg, history, mode, patient_id: patientId }, ac.signal)) {
        update((t) => {
          switch (ev.type) {
            case "status": t.steps = [...t.steps, { step: ev.step, message: ev.message }]; break;
            case "plan": t.plans = [...t.plans, ev.plan]; break;
            case "alerts": t.alerts = ev.alerts; break;
            case "chart": t.charts = [...t.charts, ev.chart]; break;
            case "sources": t.sources = ev.sources; break;
            case "token": t.content += ev.text; break;
            case "done": t.citations = ev.citations ?? []; t.streaming = false; break;
            case "error": t.error = ev.message; t.streaming = false; break;
          }
        });
      }
    } catch (e) {
      if ((e as Error).name !== "AbortError") update((t) => { t.error = String(e); });
    } finally {
      update((t) => { t.streaming = false; });
    }
  }

  return (
    <div className="flex h-full min-h-0 flex-col">
      <div className="min-h-0 flex-1 space-y-5 overflow-y-auto pr-1">
        {turns.length === 0 && (
          <div className="py-4">
            <div className="mb-3 flex items-center gap-2 text-sm text-muted"><Sparkles size={15} className="text-accent" />
              {patientId ? "Ask about this patient's record, trends or management." : "Ask the medical reference library."}
            </div>
            <div className="flex flex-wrap gap-2">
              {suggestions.map((s) => (
                <button key={s} onClick={() => send(s)} className="rounded-full border border-line bg-panel px-3 py-1.5 text-left text-[13px] hover:border-accent hover:text-accent">{s}</button>
              ))}
            </div>
          </div>
        )}
        {turns.map((t, i) => t.role === "user" ? (
          <div key={i} className="flex justify-end">
            <div className="max-w-[85%] rounded-2xl rounded-br-sm bg-accent px-3.5 py-2 text-[14.5px] text-white dark:text-black">{t.content}</div>
          </div>
        ) : (
          <AssistantTurn key={i} t={t} onOpen={(n) => setOpen(t.sources.find((s) => s.n === n) ?? null)} compact={compact} />
        ))}
        <div ref={endRef} />
      </div>

      <form className="mt-3 shrink-0" onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <div className="card flex items-end gap-2 p-2 focus-within:border-accent">
          <textarea value={input} onChange={(e) => setInput(e.target.value)} rows={1}
            onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); send(input); } }}
            placeholder={placeholder ?? "Ask a clinical question…"}
            className="max-h-40 min-h-[38px] flex-1 resize-none bg-transparent px-2 py-2 text-sm outline-none" />
          {busy ? (
            <button type="button" className="btn-ghost h-9" onClick={() => abortRef.current?.abort()}><Square size={14} /> Stop</button>
          ) : (
            <button type="submit" disabled={!input.trim()} className="btn-primary h-9 w-9 justify-center p-0" aria-label="Send"><ArrowUp size={16} /></button>
          )}
        </div>
        <div className="mt-1.5 flex items-center gap-1 text-xs text-muted">
          <span className="mr-1">Mode</span>
          {(["agentic", "fast"] as const).map((m) => (
            <button type="button" key={m} onClick={() => setMode(m)}
              className={`flex items-center gap-1 rounded-md px-2 py-0.5 ${mode === m ? "bg-accent-soft font-medium text-accent" : "hover:bg-panel-2"}`}>
              {m === "agentic" ? <Sparkles size={12} /> : <Zap size={12} />}
              {m === "agentic" ? "Agentic (plan · multi-query · reflect)" : "Fast (single pass)"}
            </button>
          ))}
        </div>
      </form>
      <SourceDrawer source={open} onClose={() => setOpen(null)} />
    </div>
  );
}

function AssistantTurn({ t, onOpen, compact }: { t: Turn; onOpen: (n: number) => void; compact: boolean }) {
  const [showTrace, setShowTrace] = useState(false);
  const [showAll, setShowAll] = useState(false);
  const cited = t.sources.filter((s) => t.citations.includes(s.n));
  const listed = showAll || !t.citations.length ? t.sources : cited;
  const queries = t.plans.flatMap((p) => [...(p.note_queries ?? []), ...(p.kb_queries ?? []), ...(p.followup_queries ?? [])]);

  return (
    <div className="space-y-2.5">
      {t.alerts.length > 0 && <AlertsBanner alerts={t.alerts.filter((a) => a.severity === "critical").slice(0, 3)} compact />}

      <button onClick={() => setShowTrace((v) => !v)} className="flex items-center gap-1.5 text-xs text-muted hover:text-fg">
        {t.streaming ? <Spinner size={11} /> : <Check size={13} className="text-ok" />}
        {t.streaming ? (t.steps.at(-1)?.message ?? "Starting…") : `Agent trace · ${t.steps.length} steps · ${queries.length} queries · ${t.sources.length} sources`}
        {showTrace ? <ChevronDown size={13} /> : <ChevronRight size={13} />}
      </button>
      {showTrace && (
        <div className="rounded-lg border border-line bg-panel-2 p-3 text-xs">
          <ol className="space-y-1">
            {t.steps.map((s, i) => <li key={i} className="flex gap-2"><span className="w-4 text-right text-muted">{i + 1}.</span>{s.message}</li>)}
          </ol>
          {t.plans.map((p, i) => (
            <div key={i} className="mt-2 space-y-1 border-t border-line pt-2">
              {p.standalone_question && <div><span className="text-muted">Rewritten question:</span> {p.standalone_question}</div>}
              {p.missing && <div><span className="text-muted">Evidence gap:</span> {p.missing}</div>}
              {[["Note queries", p.note_queries], ["Reference queries", p.kb_queries], ["Follow-up queries", p.followup_queries], ["Lab trends", p.lab_tests]].map(([label, xs]) =>
                (xs as string[] | undefined)?.length ? (
                  <div key={label as string}><span className="text-muted">{label as string}:</span> {(xs as string[]).map((q) => <span key={q} className="mr-1 inline-block rounded bg-panel px-1.5 py-0.5">{q}</span>)}</div>
                ) : null)}
            </div>
          ))}
        </div>
      )}

      {t.charts.length > 0 && (
        <div className={`grid gap-3 ${t.charts.length > 1 && !compact ? "md:grid-cols-2" : ""}`}>
          {t.charts.map((c) => <div key={c.code} className="card p-3"><TrendChart series={c} height={170} /></div>)}
        </div>
      )}

      {(t.content || t.streaming) && (
        <CitedMarkdown text={t.content} sources={t.sources} onOpen={onOpen} streaming={t.streaming && !!t.content} />
      )}
      {t.error && <div className="rounded-lg border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical">{t.error}</div>}

      {t.sources.length > 0 && !t.streaming && (
        <div>
          <div className="mb-1.5 flex items-center gap-2">
            <span className="label">{t.citations.length ? `Cited sources (${cited.length})` : `Sources (${t.sources.length})`}</span>
            {t.citations.length > 0 && t.sources.length > cited.length && (
              <button className="text-xs text-accent" onClick={() => setShowAll((v) => !v)}>{showAll ? "Show cited only" : `Show all ${t.sources.length}`}</button>
            )}
          </div>
          <div className="grid gap-1.5 sm:grid-cols-2">
            {listed.map((s) => {
              const Icon = SRC_ICON[s.kind];
              return (
                <button key={s.n} onClick={() => onOpen(s.n)} className="flex items-start gap-2 rounded-lg border border-line bg-panel p-2 text-left hover:border-accent">
                  <span className="grid h-5 w-5 shrink-0 place-items-center rounded bg-panel-2 text-[10.5px] font-bold">{s.n}</span>
                  <span className="min-w-0">
                    <span className="flex items-center gap-1 truncate text-[12.5px] font-medium"><Icon size={12} className="shrink-0 text-muted" /><span className="truncate">{s.title}</span></span>
                    <span className="line-clamp-2 text-[11.5px] text-muted">{s.text}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
