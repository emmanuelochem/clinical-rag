"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { FileUp, Globe, Search, Trash2, ExternalLink } from "lucide-react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { fmtDate, getJSON, sendJSON } from "@/lib/api";
import type { KbDocument } from "@/lib/types";
import { Empty, Spinner } from "@/components/ui";

interface Hit { chunk: { id: string; doc_id: string; text: string; headings: string[]; page_start: number | null }; doc_title: string; score: number; rerank_score: number | null; vector_rank: number | null; keyword_rank: number | null }

const STATUS: Record<string, string> = { ready: "bg-ok-soft text-ok", error: "bg-critical-soft text-critical", pending: "bg-panel-2 text-muted", processing: "bg-info-soft text-info" };

export default function KnowledgePage() {
  const [docs, setDocs] = useState<KbDocument[]>([]);
  const [url, setUrl] = useState("");
  const [busy, setBusy] = useState(false);
  const [drag, setDrag] = useState(false);
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<Hit[] | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const fileRef = useRef<HTMLInputElement>(null);

  const load = useCallback(() => getJSON<KbDocument[]>("/api/documents?scope=kb").then(setDocs).catch((e) => setMsg(String(e))), []);
  useEffect(() => { load(); }, [load]);
  useEffect(() => {
    if (!docs.some((d) => d.status === "pending" || d.status === "processing")) return;
    const id = setInterval(load, 1500);
    return () => clearInterval(id);
  }, [docs, load]);

  async function upload(files: FileList | File[]) {
    const fd = new FormData();
    [...files].forEach((f) => fd.append("files", f));
    setBusy(true); setMsg(null);
    try {
      const r = await fetch("/api/documents", { method: "POST", body: fd });
      if (!r.ok) throw new Error(await r.text());
      await load();
    } catch (e) { setMsg(String(e)); } finally { setBusy(false); }
  }

  async function addUrl() {
    if (!url.trim()) return;
    setBusy(true); setMsg(null);
    try { await sendJSON("/api/documents/url", { url: url.trim() }); setUrl(""); await load(); } catch (e) { setMsg(String(e)); } finally { setBusy(false); }
  }

  async function search() {
    if (!q.trim()) return;
    setHits(null);
    setHits(await sendJSON<Hit[]>("/api/search", { query: q, scope: "kb", top_k: 6 }));
  }

  return (
    <div className="space-y-5">
      <div>
        <h1 className="text-xl font-semibold">Knowledge base</h1>
        <p className="text-sm text-muted">Medical reference material the assistant cites. Add licensed guidelines, protocols or openly licensed sources (e.g. MedlinePlus topic pages).</p>
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
          onDrop={(e) => { e.preventDefault(); setDrag(false); upload(e.dataTransfer.files); }}
          onClick={() => fileRef.current?.click()}
          className={`card flex cursor-pointer flex-col items-center justify-center gap-1 border-dashed p-6 text-center ${drag ? "border-accent bg-accent-soft" : ""}`}>
          <FileUp className="text-accent" />
          <div className="text-sm font-medium">Drop files or click to upload</div>
          <div className="text-xs text-muted">PDF, DOCX, HTML, Markdown, TXT, CSV · structure-aware parsing (headings, tables, pages)</div>
          <input ref={fileRef} type="file" multiple hidden accept=".pdf,.docx,.html,.htm,.md,.markdown,.txt,.csv" onChange={(e) => e.target.files && upload(e.target.files)} />
        </div>
        <div className="card p-4">
          <div className="label mb-2 flex items-center gap-1"><Globe size={12} />Ingest a web page or PDF URL</div>
          <div className="flex gap-2">
            <input className="input" value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://medlineplus.gov/heartfailure.html" onKeyDown={(e) => e.key === "Enter" && addUrl()} />
            <button className="btn-primary shrink-0" onClick={addUrl} disabled={busy}>Add</button>
          </div>
          <p className="mt-2 text-xs text-muted">Bulk-load MedlinePlus (public domain, NLM): download the health-topics XML from medlineplus.gov/xml.html, then run <code className="rounded bg-panel-2 px-1">python -m app.seed --medlineplus &lt;file.xml&gt;</code>.</p>
        </div>
      </div>
      {msg && <div className="rounded-lg border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical">{msg}</div>}

      <div className="card p-4">
        <div className="label mb-2">Test retrieval (hybrid search + rerank)</div>
        <div className="flex gap-2">
          <input className="input" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === "Enter" && search()} placeholder="e.g. peaked T waves potassium" />
          <button className="btn-ghost shrink-0" onClick={search}><Search size={14} />Search</button>
        </div>
        {hits && (hits.length === 0 ? <div className="mt-3 text-sm text-muted">No results.</div> : (
          <ol className="mt-3 space-y-2">
            {hits.map((h, i) => (
              <li key={h.chunk.id} className="rounded-lg border border-line p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs text-muted">
                  <span className="font-semibold text-fg">{i + 1}. {h.doc_title}</span>
                  {h.chunk.headings.length > 1 && <span>› {h.chunk.headings.slice(1).join(" › ")}</span>}
                  <span className="ml-auto font-mono">score {h.score.toFixed(3)} · vec #{h.vector_rank ?? "—"} · bm25 #{h.keyword_rank ?? "—"}{h.rerank_score != null ? ` · rerank ${h.rerank_score.toFixed(2)}` : ""}</span>
                </div>
                <div className="prose-clin mt-1 line-clamp-4 text-sm"><ReactMarkdown remarkPlugins={[remarkGfm]}>{h.chunk.text}</ReactMarkdown></div>
              </li>
            ))}
          </ol>
        ))}
      </div>

      <div className="card overflow-hidden">
        <div className="flex items-center justify-between border-b border-line px-4 py-2.5">
          <span className="text-sm font-semibold">Documents ({docs.length})</span>
          <span className="text-xs text-muted">{docs.reduce((a, d) => a + d.num_chunks, 0)} chunks indexed</span>
        </div>
        {docs.length === 0 ? <div className="p-4"><Empty>No documents yet.</Empty></div> : (
          <ul>
            {docs.map((d) => (
              <li key={d.id} className="flex flex-wrap items-center gap-3 border-t border-line px-4 py-2.5 first:border-0">
                <div className="min-w-0 flex-1">
                  <div className="truncate text-sm font-medium">{d.title}</div>
                  <div className="truncate text-xs text-muted">{d.source} · {fmtDate(d.created_at.slice(0, 10))}{d.error ? ` · ${d.error}` : ""}</div>
                </div>
                <span className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS[d.status]}`}>{d.status === "processing" ? <><Spinner size={10} /> processing</> : d.status}</span>
                <span className="w-20 text-right text-xs tabular-nums text-muted">{d.num_chunks} chunks</span>
                {(d.has_file || d.source.startsWith("http")) && (
                  <a href={d.source.startsWith("http") ? d.source : `/api/documents/${d.id}/file`} target="_blank" rel="noreferrer" className="rounded p-1 text-muted hover:bg-panel-2" aria-label="Open"><ExternalLink size={15} /></a>
                )}
                <button className="rounded p-1 text-muted hover:bg-critical-soft hover:text-critical" aria-label="Delete"
                  onClick={async () => { if (confirm(`Delete "${d.title}" from the knowledge base?`)) { await fetch(`/api/documents/${d.id}`, { method: "DELETE" }); load(); } }}>
                  <Trash2 size={15} />
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
