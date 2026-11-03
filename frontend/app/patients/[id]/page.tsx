"use client";

import { use, useEffect, useMemo, useState } from "react";
import Link from "next/link";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import { ArrowLeft, Pill, ShieldAlert, Stethoscope } from "lucide-react";
import { fmtDate, getJSON } from "@/lib/api";
import type { Note, Obs, PatientDetail, Series } from "@/lib/types";
import { Chat } from "@/components/Chat";
import { DifferentialPanel } from "@/components/DifferentialPanel";
import { TrendChart } from "@/components/TrendChart";
import { AlertsBanner, Empty, FlagBadge, Spinner } from "@/components/ui";

type Tab = "overview" | "trends" | "notes" | "differential";

export default function PatientPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const [d, setD] = useState<PatientDetail | null>(null);
  const [notes, setNotes] = useState<Note[]>([]);
  const [tab, setTab] = useState<Tab>("overview");
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    getJSON<PatientDetail>(`/api/patients/${id}`).then(setD).catch((e) => setError(String(e)));
    getJSON<Note[]>(`/api/patients/${id}/notes`).then(setNotes).catch(() => {});
  }, [id]);

  const edNote = notes.find((n) => n.type === "ED triage note" && n.date === d?.last_encounter?.date);
  const initialSymptoms = useMemo(() => {
    if (!edNote) return [];
    const reason = d?.last_encounter?.reason?.toLowerCase() ?? "";
    return reason.split(/ and |, /).map((s) => s.trim()).filter(Boolean);
  }, [edNote, d]);
  const hpi = edNote?.text.match(/## History of present illness\s+([\s\S]*?)\n\n##/)?.[1]?.split(". Past medical")[0] ?? "";

  if (error) return <div className="rounded-lg border border-critical/30 bg-critical-soft p-3 text-sm text-critical">{error}</div>;
  if (!d) return <div className="flex items-center gap-2 text-sm text-muted"><Spinner /> Loading record…</div>;
  const p = d.patient;
  const suggestions = [
    "Summarise this patient's active problems and recent changes",
    ...(d.abnormal_labs.slice(0, 2).map((o) => `How has the ${o.name} trended over time?`)),
    d.last_encounter?.type.startsWith("Emergency") ? `What should I consider for today's ${d.last_encounter.reason.toLowerCase()}?` : "Are there any medication safety concerns?",
    "Is blood pressure at target per guidelines?",
  ];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start gap-4">
        <Link href="/" className="mt-1 rounded-lg p-1.5 text-muted hover:bg-panel-2" aria-label="Back"><ArrowLeft size={18} /></Link>
        <div className="min-w-0 flex-1">
          <h1 className="text-xl font-semibold">{p.first_name} {p.last_name}
            <span className="ml-2 align-middle text-sm font-normal text-muted">{p.age} y · {p.sex} · MRN {p.mrn}</span></h1>
          <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
            <span>DOB {fmtDate(p.birth_date)}</span><span>Blood type {p.blood_type}</span><span>PCP {p.primary_provider}</span>
            <span>Last encounter: {d.last_encounter ? `${d.last_encounter.type} · ${fmtDate(d.last_encounter.date)}` : "—"}</span>
          </div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          {d.allergies.length ? d.allergies.map((a) => (
            <span key={a.id} className={`flex items-center gap-1 rounded-md px-2 py-1 text-xs font-semibold ${a.severity === "severe" ? "bg-critical text-white" : "bg-critical-soft text-critical"}`}>
              <ShieldAlert size={12} /> {a.substance} ({a.reaction})
            </span>
          )) : <span className="rounded-md bg-ok-soft px-2 py-1 text-xs font-semibold text-ok">NKDA</span>}
        </div>
      </div>

      <AlertsBanner alerts={d.alerts} />

      <div className="grid gap-4 lg:grid-cols-12">
        <section className="min-w-0 lg:col-span-7">
          <div className="mb-3 flex gap-1 overflow-x-auto border-b border-line">
            {(["overview", "trends", "notes", "differential"] as Tab[]).map((t) => (
              <button key={t} onClick={() => setTab(t)}
                className={`-mb-px shrink-0 border-b-2 px-3 py-2 text-sm capitalize ${tab === t ? "border-accent font-medium text-accent" : "border-transparent text-muted hover:text-fg"}`}>
                {t === "differential" ? "Differential Dx" : t}
                {t === "notes" && <span className="ml-1 text-xs text-muted">({notes.length})</span>}
              </button>
            ))}
          </div>
          {tab === "overview" && <Overview d={d} pid={id} />}
          {tab === "trends" && <Trends d={d} pid={id} />}
          {tab === "notes" && <Notes notes={notes} />}
          {tab === "differential" && <DifferentialPanel patientId={id} initialSymptoms={initialSymptoms} initialNotes={hpi} />}
        </section>

        <aside className="lg:col-span-5">
          <div className="card flex flex-col p-4 lg:sticky lg:top-[96px] lg:h-[calc(100vh-120px)]">
            <div className="mb-2 flex items-center gap-2 text-sm font-semibold"><Stethoscope size={16} className="text-accent" />Clinical assistant
              <span className="text-xs font-normal text-muted">scoped to this patient + reference library</span></div>
            <div className="min-h-[420px] flex-1 lg:min-h-0">
              <Chat patientId={id} suggestions={suggestions} compact placeholder={`Ask about ${p.first_name}'s record…`} />
            </div>
          </div>
        </aside>
      </div>
    </div>
  );
}

function ObsTable({ rows }: { rows: Obs[] }) {
  return (
    <table className="w-full text-sm">
      <tbody>
        {rows.map((o) => (
          <tr key={o.code} className="border-t border-line first:border-0">
            <td className="py-1.5 pr-2">{o.name}</td>
            <td className={`py-1.5 text-right font-medium tabular-nums ${o.interpretation === "N" ? "" : o.interpretation.length === 2 ? "text-critical" : "text-warning"}`}>
              {o.value} <span className="text-xs font-normal text-muted">{o.unit}</span><FlagBadge flag={o.interpretation} />
            </td>
            <td className="hidden py-1.5 pl-3 text-right text-xs text-muted sm:table-cell">
              {o.ref_low ?? ""}{o.ref_low != null || o.ref_high != null ? "–" : ""}{o.ref_high ?? ""}
            </td>
            <td className="py-1.5 pl-3 text-right text-xs whitespace-nowrap text-muted">{fmtDate(o.date)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function Overview({ d, pid }: { d: PatientDetail; pid: string }) {
  const [spark, setSpark] = useState<Series[]>([]);
  useEffect(() => {
    const codes = [...new Set([...d.abnormal_labs.map((o) => o.code), "8480-6"])].slice(0, 4);
    getJSON<Series[]>(`/api/patients/${pid}/series?codes=${codes.join(",")}`).then(setSpark).catch(() => {});
  }, [d, pid]);
  const active = d.conditions.filter((c) => c.status === "active");
  const meds = d.medications.filter((m) => m.status === "active");

  return (
    <div className="space-y-4">
      {d.news2 && (
        <div className="card flex flex-wrap items-center gap-3 p-3 text-sm">
          <span className="label">NEWS2 (latest vitals)</span>
          <span className={`rounded-md px-2 py-0.5 font-bold ${d.news2.risk === "high" ? "bg-critical text-white" : d.news2.risk === "low" ? "bg-ok-soft text-ok" : "bg-warning-soft text-warning"}`}>{d.news2.score} · {d.news2.risk} risk</span>
          <span className="text-xs text-muted">{Object.entries(d.news2.components).map(([k, v]) => `${k} ${v}`).join(" · ")}</span>
        </div>
      )}
      {spark.length > 0 && (
        <div className="grid gap-3 sm:grid-cols-2">
          {spark.map((s) => <div key={s.code} className="card p-3"><TrendChart series={s.code === "8480-6" ? { ...s, name: "Systolic BP" } : s} height={130} /></div>)}
        </div>
      )}
      <div className="grid gap-4 md:grid-cols-2">
        <div className="card p-4">
          <div className="label mb-2">Active problems ({active.length})</div>
          {active.length ? <ul className="space-y-1.5 text-sm">{active.map((c) => (
            <li key={c.id} className="flex justify-between gap-2"><span>{c.display}</span><span className="shrink-0 font-mono text-xs text-muted">{c.code} · {c.onset_date.slice(0, 4)}</span></li>
          ))}</ul> : <div className="text-sm text-muted">None recorded</div>}
        </div>
        <div className="card p-4">
          <div className="label mb-2 flex items-center gap-1"><Pill size={12} />Medications ({meds.length})</div>
          {meds.length ? <ul className="space-y-1.5 text-sm">{meds.map((m) => (
            <li key={m.id}><span className="font-medium">{m.name}</span> {m.dose} <span className="text-muted">{m.frequency}</span>
              <div className="text-xs text-muted">since {fmtDate(m.start_date)}</div></li>
          ))}</ul> : <div className="text-sm text-muted">None</div>}
        </div>
        <div className="card p-4"><div className="label mb-2">Latest vitals</div><ObsTable rows={d.latest_vitals} /></div>
        <div className="card p-4"><div className="label mb-2">Latest labs</div><ObsTable rows={[...d.latest_labs].sort((a, b) => (a.interpretation === "N" ? 1 : 0) - (b.interpretation === "N" ? 1 : 0))} /></div>
      </div>
      <div className="card p-4">
        <div className="label mb-2">Encounter timeline</div>
        <ol className="relative ml-2 border-l border-line">
          {d.encounters.map((e) => (
            <li key={e.id} className="mb-3 ml-4">
              <span className={`absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full ${e.type.startsWith("Emergency") ? "bg-critical" : "bg-accent"}`} />
              <div className="text-sm"><span className="font-medium">{e.type}</span> · {e.reason}</div>
              <div className="text-xs text-muted">{fmtDate(e.date)} · {e.provider}</div>
            </li>
          ))}
        </ol>
      </div>
    </div>
  );
}

function Trends({ d, pid }: { d: PatientDetail; pid: string }) {
  const defaults = useMemo(() => [...new Set(["8480-6", ...d.abnormal_labs.map((o) => o.code)])].slice(0, 4), [d]);
  const [sel, setSel] = useState<string[]>(defaults);
  const [series, setSeries] = useState<Series[]>([]);
  useEffect(() => {
    if (!sel.length) { setSeries([]); return; }
    getJSON<Series[]>(`/api/patients/${pid}/series?codes=${[...sel, ...(sel.includes("8480-6") ? ["8462-4"] : [])].join(",")}`).then((all) => {
      const dia = all.find((s) => s.code === "8462-4");
      setSeries(all.filter((s) => sel.includes(s.code)).map((s) => (s.code === "8480-6" && dia && !sel.includes("8462-4") ? { ...s, name: "Blood pressure", companion: dia } : s)));
    });
  }, [sel, pid]);
  const panels = d.available.reduce<Record<string, typeof d.available>>((acc, a) => { (acc[a.panel] ??= []).push(a); return acc; }, {});

  return (
    <div className="space-y-4">
      <div className="card space-y-2 p-3">
        {Object.entries(panels).map(([panel, items]) => (
          <div key={panel} className="flex flex-wrap items-center gap-1.5">
            <span className="w-24 shrink-0 text-xs text-muted">{panel}</span>
            {items.map((a) => (
              <button key={a.code} onClick={() => setSel((s) => s.includes(a.code) ? s.filter((x) => x !== a.code) : [...s, a.code])}
                className={`rounded-full border px-2 py-0.5 text-xs ${sel.includes(a.code) ? "border-accent bg-accent-soft text-accent" : "border-line hover:border-accent"}`}>
                {a.name} <span className="text-muted">{a.count}</span>
              </button>
            ))}
          </div>
        ))}
      </div>
      {series.length === 0 ? <Empty>Select labs or vitals above to chart them.</Empty> : (
        <div className="grid gap-3 md:grid-cols-2">
          {series.map((s) => <div key={s.code} className="card p-3"><TrendChart series={s} height={190} /></div>)}
        </div>
      )}
    </div>
  );
}

function Notes({ notes }: { notes: Note[] }) {
  const [sel, setSel] = useState<Note | null>(notes[0] ?? null);
  useEffect(() => { setSel(notes[0] ?? null); }, [notes]);
  if (!notes.length) return <Empty>No notes.</Empty>;
  return (
    <div className="grid gap-3 md:grid-cols-[220px_1fr]">
      <div className="card max-h-[70vh] overflow-y-auto p-1">
        {notes.map((n) => (
          <button key={n.id} onClick={() => setSel(n)}
            className={`block w-full rounded-lg px-3 py-2 text-left ${sel?.id === n.id ? "bg-accent-soft" : "hover:bg-panel-2"}`}>
            <div className={`text-sm font-medium ${n.type.startsWith("ED") ? "text-critical" : ""}`}>{n.type}</div>
            <div className="text-xs text-muted">{fmtDate(n.date)}</div>
          </button>
        ))}
      </div>
      {sel && (
        <article className="card p-4">
          <div className="label mb-2">{sel.type} · {fmtDate(sel.date)} · {sel.author}</div>
          <div className="prose-clin"><ReactMarkdown remarkPlugins={[remarkGfm]}>{sel.text}</ReactMarkdown></div>
        </article>
      )}
    </div>
  );
}
