"use client";

import { useEffect, useState } from "react";
import { BookOpen, ClipboardList, ExternalLink, FileText, X } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Note, Series, Source } from "@/lib/types";
import { fmtDate, getJSON } from "@/lib/api";
import { TrendChart } from "./TrendChart";

const KIND = {
  record: { label: "Patient record", icon: ClipboardList, tone: "text-accent" },
  note: { label: "Clinical note", icon: FileText, tone: "text-info" },
  kb: { label: "Medical reference", icon: BookOpen, tone: "text-muted" },
};

export function SourceDrawer({ source, onClose }: { source: Source | null; onClose: () => void }) {
  const [series, setSeries] = useState<Series | null>(null);
  const [note, setNote] = useState<Note | null>(null);

  useEffect(() => {
    setSeries(null); setNote(null);
    if (source?.kind === "record" && source.chart_code && source.patient_id) {
      getJSON<Series[]>(`/api/patients/${source.patient_id}/series?codes=${source.chart_code}`).then((s) => setSeries(s[0] ?? null)).catch(() => {});
    }
  }, [source]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  if (!source) return null;
  const k = KIND[source.kind];
  const Icon = k.icon;
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-black/25" onClick={onClose}>
      <aside className="flex h-full w-full max-w-xl flex-col border-l border-line bg-panel shadow-2xl" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start gap-3 border-b border-line p-4">
          <span className="mt-0.5 grid h-7 w-7 shrink-0 place-items-center rounded-md bg-panel-2 text-sm font-bold">{source.n}</span>
          <div className="min-w-0 flex-1">
            <div className={`flex items-center gap-1 text-xs font-medium ${k.tone}`}><Icon size={13} />{k.label}</div>
            <div className="font-semibold leading-snug">{source.title}</div>
            {source.headings && source.headings.length > 0 && (
              <div className="mt-0.5 text-xs text-muted">{source.headings.join(" › ")}{source.page ? ` · page ${source.page}` : ""}</div>
            )}
          </div>
          <button onClick={onClose} className="rounded p-1 text-muted hover:bg-panel-2" aria-label="Close"><X size={18} /></button>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto p-4">
          {series && <div className="card p-3"><TrendChart series={series} /></div>}

          <div>
            {source.context_before && <p className="mb-2 whitespace-pre-wrap text-sm text-muted line-clamp-4">{source.context_before}</p>}
            <div className="rounded-lg border-l-4 border-accent bg-accent-soft/50 p-3 text-sm">
              <div className="prose-clin"><ReactMarkdown remarkPlugins={[remarkGfm]}>{source.text}</ReactMarkdown></div>
            </div>
            {source.context_after && <p className="mt-2 whitespace-pre-wrap text-sm text-muted line-clamp-4">{source.context_after}</p>}
          </div>

          {source.kind === "note" && source.doc_id && !note && (
            <button className="btn-ghost" onClick={() => getJSON<Note>(`/api/notes/${source.doc_id}`).then(setNote)}>
              <FileText size={14} /> Open full note
            </button>
          )}
          {note && (
            <div className="card p-4">
              <div className="label mb-2">{note.type} · {fmtDate(note.date)} · {note.author}</div>
              <div className="prose-clin"><ReactMarkdown remarkPlugins={[remarkGfm]}>{note.text}</ReactMarkdown></div>
            </div>
          )}
          {source.kind === "kb" && source.doc_id && (
            <a className="btn-ghost w-fit" href={source.source?.startsWith("http") ? source.source : `/api/documents/${source.doc_id}/file${source.page ? `#page=${source.page}` : ""}`}
              target="_blank" rel="noreferrer"><ExternalLink size={14} /> Open original</a>
          )}

          {source.kind !== "record" && (
            <div className="rounded-lg bg-panel-2 p-3 text-xs text-muted">
              <div className="label mb-1.5">Retrieval diagnostics</div>
              <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                <span>Final score</span><span className="font-mono text-fg">{source.score?.toFixed(3) ?? "—"}</span>
                <span>Rerank score</span><span className="font-mono text-fg">{source.rerank_score?.toFixed(3) ?? "not reranked"}</span>
                <span>Vector rank</span><span className="font-mono text-fg">{source.vector_rank ?? "—"}</span>
                <span>Keyword (BM25) rank</span><span className="font-mono text-fg">{source.keyword_rank ?? "—"}</span>
              </div>
              {source.matched_queries && source.matched_queries.length > 0 && (
                <div className="mt-2">Matched queries: {source.matched_queries.map((q) => <span key={q} className="mr-1 mt-1 inline-block rounded bg-panel px-1.5 py-0.5 text-fg">{q}</span>)}</div>
              )}
            </div>
          )}
        </div>
      </aside>
    </div>
  );
}
