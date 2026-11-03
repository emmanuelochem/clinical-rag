"use client";

import { useEffect, useState } from "react";
import { Bar, BarChart, CartesianGrid, LabelList, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Table2, BarChart3 } from "lucide-react";
import { getJSON } from "@/lib/api";
import { Spinner } from "@/components/ui";

interface Cohort {
  n_patients: number; sex: Record<string, number>;
  age_bands: { band: string; patients: number }[];
  prevalence: { condition: string; code: string; patients: number }[];
  control: { measure: string; condition_code: string; controlled: number; uncontrolled: number }[];
  a1c_trend: { period: string; mean: number; n: number }[];
  abnormal_labs: { name: string; n: number }[];
  encounters_by_month: { month: string; n: number }[];
}

const tip = { contentStyle: { background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }, cursor: { fill: "var(--panel-2)" } };
const axis = { tick: { fontSize: 11, fill: "var(--muted)" }, stroke: "var(--border)" };

function ChartCard({ title, subtitle, rows, children, className = "" }: {
  title: string; subtitle?: string; rows: Record<string, string | number>[]; children: React.ReactNode; className?: string;
}) {
  const [table, setTable] = useState(false);
  const cols = rows[0] ? Object.keys(rows[0]) : [];
  return (
    <div className={`card p-4 ${className}`}>
      <div className="mb-2 flex items-start justify-between gap-2">
        <div><div className="text-sm font-semibold">{title}</div>{subtitle && <div className="text-xs text-muted">{subtitle}</div>}</div>
        <button className="rounded p-1 text-muted hover:bg-panel-2" onClick={() => setTable((t) => !t)} aria-label={table ? "Show chart" : "Show table"} title={table ? "Show chart" : "Show table"}>
          {table ? <BarChart3 size={15} /> : <Table2 size={15} />}
        </button>
      </div>
      {table ? (
        <div className="max-h-64 overflow-auto">
          <table className="w-full text-sm"><thead><tr>{cols.map((c) => <th key={c} className="border-b border-line py-1 text-left text-xs font-medium text-muted">{c}</th>)}</tr></thead>
            <tbody>{rows.map((r, i) => <tr key={i}>{cols.map((c) => <td key={c} className="border-b border-line py-1 tabular-nums">{r[c]}</td>)}</tr>)}</tbody></table>
        </div>
      ) : children}
    </div>
  );
}

export default function CohortPage() {
  const [c, setC] = useState<Cohort | null>(null);
  const [err, setErr] = useState<string | null>(null);
  useEffect(() => { getJSON<Cohort>("/api/cohort").then(setC).catch((e) => setErr(String(e))); }, []);
  if (err) return <div className="text-sm text-critical">{err}</div>;
  if (!c) return <div className="flex items-center gap-2 text-sm text-muted"><Spinner /> Loading cohort…</div>;

  const prevalence = c.prevalence.map((p) => ({ condition: p.condition.replace(/, unspecified|without complications|\(primary\) |\(congestive\) /g, "").trim(), patients: p.patients }));
  const control = c.control.map((x) => ({ measure: x.measure, "At target": x.controlled, "Not at target": x.uncontrolled }));
  const totalEnc = c.encounters_by_month.reduce((a, b) => a + b.n, 0);
  const latestA1c = c.a1c_trend.at(-1);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Cohort analytics</h1>
        <p className="text-sm text-muted">Population view across all synthetic patients.</p>
      </div>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {[
          ["Patients", c.n_patients, `${c.sex.female ?? 0} female · ${c.sex.male ?? 0} male`],
          ["Active diagnoses", c.prevalence.reduce((a, b) => a + b.patients, 0), `${c.prevalence.length} distinct conditions`],
          ["Encounters (24 mo)", totalEnc, `${(totalEnc / Math.max(c.n_patients, 1)).toFixed(1)} per patient`],
          ["Mean HbA1c, diabetics", latestA1c ? `${latestA1c.mean}%` : "—", latestA1c ? `${latestA1c.period} · n=${latestA1c.n}` : ""],
        ].map(([label, value, sub]) => (
          <div key={label as string} className="card p-4">
            <div className="label">{label}</div>
            <div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div>
            <div className="text-xs text-muted">{sub}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard title="Condition prevalence" subtitle="Patients with each active diagnosis" rows={prevalence}>
          <div style={{ height: Math.max(220, prevalence.length * 26) }}>
            <ResponsiveContainer>
              <BarChart data={prevalence} layout="vertical" margin={{ left: 8, right: 28 }}>
                <CartesianGrid horizontal={false} stroke="var(--grid)" />
                <XAxis type="number" allowDecimals={false} {...axis} />
                <YAxis type="category" dataKey="condition" width={190} {...axis} interval={0} />
                <Tooltip {...tip} />
                <Bar isAnimationActive={false} dataKey="patients" name="Patients" fill="var(--series-1)" radius={[0, 4, 4, 0]} barSize={14}>
                  <LabelList dataKey="patients" position="right" style={{ fontSize: 11, fill: "var(--muted)" }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <div className="space-y-4">
          <ChartCard title="Treatment targets" subtitle="Latest value per patient with the relevant diagnosis" rows={control}>
            <div className="space-y-3">
              {c.control.map((x) => {
                const tot = x.controlled + x.uncontrolled;
                const pct = Math.round((x.controlled / Math.max(tot, 1)) * 100);
                return (
                  <div key={x.measure}>
                    <div className="mb-1 flex justify-between text-sm"><span>{x.measure}</span><span className="tabular-nums text-muted"><span className="font-semibold text-fg">{pct}%</span> at target ({x.controlled}/{tot})</span></div>
                    <div className="flex h-3 gap-0.5 overflow-hidden rounded">
                      <div className="rounded-l bg-ok" style={{ width: `${pct}%` }} title={`At target: ${x.controlled}`} />
                      <div className="rounded-r bg-critical/70" style={{ width: `${100 - pct}%` }} title={`Not at target: ${x.uncontrolled}`} />
                    </div>
                  </div>
                );
              })}
              <div className="flex gap-4 text-xs text-muted">
                <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-ok" />At target</span>
                <span className="flex items-center gap-1"><span className="h-2 w-2 rounded-sm bg-critical/70" />Not at target</span>
              </div>
            </div>
          </ChartCard>
          <ChartCard title="Age distribution" rows={c.age_bands}>
            <div className="h-44">
              <ResponsiveContainer>
                <BarChart data={c.age_bands} margin={{ left: -20, top: 14 }}>
                  <CartesianGrid vertical={false} stroke="var(--grid)" />
                  <XAxis dataKey="band" {...axis} /><YAxis allowDecimals={false} {...axis} />
                  <Tooltip {...tip} />
                  <Bar isAnimationActive={false} dataKey="patients" name="Patients" fill="var(--series-1)" radius={[4, 4, 0, 0]} barSize={28}>
                    <LabelList dataKey="patients" position="top" style={{ fontSize: 11, fill: "var(--muted)" }} />
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </ChartCard>
        </div>

        <ChartCard title="Mean HbA1c among patients with type 2 diabetes" subtitle="By quarter; dashed line marks the common < 7% goal" rows={c.a1c_trend}>
          <div className="h-56">
            <ResponsiveContainer>
              <LineChart data={c.a1c_trend} margin={{ left: -16, right: 28 }}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="period" {...axis} /><YAxis domain={[(lo: number) => Math.floor(Math.min(lo, 7) * 2) / 2 - 0.5, (hi: number) => Math.ceil(hi * 2) / 2 + 0.5]} tickFormatter={(v: number) => v.toFixed(1)} {...axis} />
                <ReferenceLine y={7} stroke="var(--muted)" strokeDasharray="4 4" label={{ value: "7%", position: "right", fontSize: 11, fill: "var(--muted)" }} />
                <Tooltip {...tip} cursor={{ stroke: "var(--border)" }} formatter={(v) => [`${v}%`, "Mean HbA1c"]} />
                <Line dataKey="mean" stroke="var(--series-1)" strokeWidth={2} dot={{ r: 4, fill: "var(--series-1)", stroke: "var(--panel)", strokeWidth: 2 }} isAnimationActive={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <ChartCard title="Most frequent abnormal lab results" subtitle="Out-of-range results in the last 12 months" rows={c.abnormal_labs}>
          <div className="h-56">
            <ResponsiveContainer>
              <BarChart data={c.abnormal_labs} layout="vertical" margin={{ left: 8, right: 28 }}>
                <CartesianGrid horizontal={false} stroke="var(--grid)" />
                <XAxis type="number" allowDecimals={false} {...axis} />
                <YAxis type="category" dataKey="name" width={150} {...axis} interval={0} />
                <Tooltip {...tip} />
                <Bar isAnimationActive={false} dataKey="n" name="Abnormal results" fill="var(--series-1)" radius={[0, 4, 4, 0]} barSize={12}>
                  <LabelList dataKey="n" position="right" style={{ fontSize: 11, fill: "var(--muted)" }} />
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>

        <ChartCard title="Encounters per month" subtitle="Last 24 months" rows={c.encounters_by_month} className="lg:col-span-2">
          <div className="h-48">
            <ResponsiveContainer>
              <BarChart data={c.encounters_by_month} margin={{ left: -20 }}>
                <CartesianGrid vertical={false} stroke="var(--grid)" />
                <XAxis dataKey="month" {...axis} interval="preserveStartEnd" /><YAxis allowDecimals={false} {...axis} />
                <Tooltip {...tip} />
                <Bar isAnimationActive={false} dataKey="n" name="Encounters" fill="var(--series-1)" radius={[4, 4, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </div>
        </ChartCard>
      </div>
    </div>
  );
}
