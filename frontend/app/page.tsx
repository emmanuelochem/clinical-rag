"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AlertOctagon, Database, Search } from "lucide-react";
import { fmtDate, getJSON, sendJSON } from "@/lib/api";
import type { PatientRow } from "@/lib/types";
import { Empty, Spinner } from "@/components/ui";

export default function PatientsPage() {
  const [q, setQ] = useState("");
  const [rows, setRows] = useState<PatientRow[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [seeding, setSeeding] = useState(false);

  const load = (query: string) =>
    getJSON<PatientRow[]>(`/api/patients?q=${encodeURIComponent(query)}`).then((r) => { setRows(r); setError(null); }).catch((e) => setError(String(e)));

  useEffect(() => { const id = setTimeout(() => load(q), 200); return () => clearTimeout(id); }, [q]);

  const seed = async () => {
    setSeeding(true);
    try { await sendJSON("/api/admin/seed?patients=30", {}); await load(""); } catch (e) { setError(String(e)); } finally { setSeeding(false); }
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Patients</h1>
          <p className="text-sm text-muted">Sorted by critical results at the most recent encounter, then by last visit.</p>
        </div>
        <div className="relative w-full max-w-sm">
          <Search size={15} className="absolute left-3 top-2.5 text-muted" />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search name, MRN, or condition (e.g. diabetes, I50)" className="input pl-9" />
        </div>
      </div>

      {error && <div className="rounded-lg border border-critical/30 bg-critical-soft px-3 py-2 text-sm text-critical">Cannot load patients: {error}</div>}
      {rows === null && !error && <div className="flex items-center gap-2 text-sm text-muted"><Spinner /> Loading…</div>}
      {rows?.length === 0 && !q && (
        <Empty>
          <Database className="mx-auto mb-2 text-muted" />
          No patients yet. Generate a synthetic cohort and index the bundled reference library.
          <div className="mt-3"><button className="btn-primary" onClick={seed} disabled={seeding}>{seeding ? <Spinner /> : null} Generate 30 synthetic patients</button></div>
          <div className="mt-2 text-xs">Requires Ollama with the embedding model (it embeds clinical notes). This can take a minute.</div>
        </Empty>
      )}
      {rows && rows.length > 0 && (
        <div className="card overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-panel-2 text-left text-xs text-muted">
                <tr>
                  <th className="px-4 py-2.5 font-medium">Patient</th><th className="px-3 py-2.5 font-medium">MRN</th>
                  <th className="px-3 py-2.5 font-medium">Age / sex</th><th className="px-3 py-2.5 font-medium">Active problems</th>
                  <th className="px-3 py-2.5 font-medium">Last visit</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((p) => (
                  <tr key={p.id} className="border-t border-line hover:bg-panel-2/60">
                    <td className="px-4 py-2.5">
                      <Link href={`/patients/${p.id}`} className="font-medium text-accent hover:underline">{p.last_name}, {p.first_name}</Link>
                      {p.n_critical > 0 && (
                        <span className="ml-2 inline-flex items-center gap-1 rounded bg-critical px-1.5 py-0.5 text-[11px] font-semibold text-white">
                          <AlertOctagon size={11} /> {p.n_critical} critical
                        </span>
                      )}
                    </td>
                    <td className="px-3 py-2.5 font-mono text-xs text-muted">{p.mrn}</td>
                    <td className="px-3 py-2.5 whitespace-nowrap">{p.age} · {p.sex[0].toUpperCase()}</td>
                    <td className="px-3 py-2.5">
                      <div className="flex max-w-xl flex-wrap gap-1">
                        {p.conditions.length ? p.conditions.map((c) => <span key={c} className="rounded bg-panel-2 px-1.5 py-0.5 text-xs">{c.replace(/, unspecified|without complications/g, "")}</span>)
                          : <span className="text-xs text-muted">None</span>}
                      </div>
                    </td>
                    <td className="px-3 py-2.5 whitespace-nowrap text-xs">
                      {fmtDate(p.last_visit)}
                      <div className={p.last_visit_type?.startsWith("Emergency") ? "font-medium text-critical" : "text-muted"}>{p.last_visit_type}</div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  );
}
