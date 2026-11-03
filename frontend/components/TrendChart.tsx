"use client";

import { CartesianGrid, Line, LineChart, ReferenceArea, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { Series } from "@/lib/types";
import { FlagBadge } from "./ui";
import { fmtDate } from "@/lib/api";

const FLAG_COLOR: Record<string, string> = { N: "var(--series-1)", H: "var(--warning)", L: "var(--warning)", HH: "var(--critical)", LL: "var(--critical)" };

/** Time-series chart with the reference range shaded and abnormal points colour-coded. */
export function TrendChart({ series, height = 200, compact = false }: { series: Series; height?: number; compact?: boolean }) {
  const comp = series.companion;
  const byDate = new Map<string, { date: string; t: number; v?: number; flag?: string; c?: number; cflag?: string }>();
  for (const p of series.points) byDate.set(p.date, { date: p.date, t: Date.parse(p.date), v: p.value, flag: p.flag });
  for (const p of comp?.points ?? []) {
    const row = byDate.get(p.date) ?? { date: p.date, t: Date.parse(p.date) };
    row.c = p.value; row.cflag = p.flag; byDate.set(p.date, row);
  }
  const data = [...byDate.values()].sort((a, b) => a.t - b.t);
  const values = data.flatMap((d) => [d.v, d.c]).filter((x): x is number => typeof x === "number");
  const lo = Math.min(...values, series.ref_low ?? Infinity, comp?.ref_low ?? Infinity);
  const hi = Math.max(...values, series.ref_high ?? -Infinity, comp?.ref_high ?? -Infinity);
  const domain = niceDomain(lo, hi);
  const last = series.points.at(-1);
  const first = series.points[0];

  const dot = (key: "flag" | "cflag", color?: string) =>
    function Dot(props: { cx?: number; cy?: number; payload?: Record<string, string> }) {
      const { cx, cy, payload } = props;
      if (cx == null || cy == null || !payload || payload[key] == null) return <g />;
      const f = payload[key];
      return <circle cx={cx} cy={cy} r={f === "N" ? 3 : 4.5} fill={f === "N" ? (color ?? "var(--panel)") : FLAG_COLOR[f]}
        stroke={color ?? FLAG_COLOR.N} strokeWidth={1.5} />;
    };

  return (
    <div>
      {!compact && (
        <div className="mb-1 flex flex-wrap items-baseline justify-between gap-2">
          <div className="text-sm font-semibold">{series.name}{comp ? ` / ${comp.name}` : ""}
            <span className="ml-1.5 text-xs font-normal text-muted">{series.unit}</span></div>
          {last && (
            <div className="text-xs text-muted">
              Latest <span className="font-semibold text-fg">{last.value}{comp?.points.at(-1) ? `/${comp.points.at(-1)!.value}` : ""}</span>
              <FlagBadge flag={last.flag} /> · {fmtDate(last.date)}
              {first && first !== last && <> · Δ {(last.value - first.value > 0 ? "+" : "") + (last.value - first.value).toFixed(2).replace(/\.?0+$/, "")}</>}
            </div>
          )}
        </div>
      )}
      <div style={{ height }}>
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -4 }}>
            <CartesianGrid stroke="var(--grid)" vertical={false} />
            <XAxis dataKey="t" type="number" scale="time" domain={["dataMin", "dataMax"]} tick={{ fontSize: 11, fill: "var(--muted)" }}
              tickFormatter={(t) => new Date(t).toLocaleDateString(undefined, { month: "short", year: "2-digit" })} stroke="var(--border)" />
            <YAxis domain={domain} ticks={ticks(domain)} tick={{ fontSize: 11, fill: "var(--muted)" }} stroke="var(--border)" width={52}
              tickFormatter={(v: number) => fmtTick(v, domain)} />
            {(series.ref_low != null || series.ref_high != null) && (
              <ReferenceArea y1={series.ref_low ?? domain[0]} y2={series.ref_high ?? domain[1]} fill="var(--range)" ifOverflow="hidden" />
            )}
            {series.ref_high != null && <ReferenceLine y={series.ref_high} stroke="var(--accent)" strokeDasharray="3 3" strokeOpacity={0.5} />}
            {series.ref_low != null && <ReferenceLine y={series.ref_low} stroke="var(--accent)" strokeDasharray="3 3" strokeOpacity={0.5} />}
            <Tooltip
              contentStyle={{ background: "var(--panel)", border: "1px solid var(--border)", borderRadius: 8, fontSize: 12 }}
              labelFormatter={(t) => fmtDate(new Date(t as number).toISOString().slice(0, 10))}
              formatter={(v, name) => [`${v} ${series.unit}`, name === "v" ? series.name : comp?.name ?? ""]} />
            <Line type="monotone" dataKey="v" stroke="var(--series-1)" strokeWidth={2} dot={dot("flag")} connectNulls isAnimationActive={false} />
            {comp && <Line type="monotone" dataKey="c" stroke="var(--series-2)" strokeWidth={2} dot={dot("cflag", "var(--series-2)")} connectNulls isAnimationActive={false} />}
          </LineChart>
        </ResponsiveContainer>
      </div>
      {comp && (
        <div className="mt-1 flex gap-3 text-[11px] text-muted">
          <span className="flex items-center gap-1"><span className="h-0.5 w-3 rounded bg-[var(--series-1)]" />{series.name.replace("Blood pressure", "Systolic")}</span>
          <span className="flex items-center gap-1"><span className="h-0.5 w-3 rounded bg-[var(--series-2)]" />{comp.name}</span>
        </div>
      )}
      {!compact && (
        <div className="mt-1 text-[11px] text-muted">
          Shaded: reference range {refText(series.ref_low, series.ref_high)} {series.unit}. Amber/red points are out of range (H/L, critical).
        </div>
      )}
    </div>
  );
}

/** Round the y-domain to a "nice" step so tick labels are clean numbers. */
function niceStep(span: number) {
  const raw = span / 4;
  const mag = 10 ** Math.floor(Math.log10(raw || 1));
  return [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => s >= raw) ?? 10 * mag;
}
function niceDomain(lo: number, hi: number): [number, number] {
  if (!isFinite(lo) || !isFinite(hi)) return [0, 1];
  if (hi === lo) { hi += Math.abs(hi) * 0.1 || 1; lo -= Math.abs(lo) * 0.1 || 1; }
  const step = niceStep(hi - lo);
  return [Math.max(0, Math.floor(lo / step) * step), Math.ceil(hi / step) * step];
}
function ticks([lo, hi]: [number, number]) {
  const step = niceStep(hi - lo);
  const out: number[] = [];
  for (let v = lo; v <= hi + step / 1000; v += step) out.push(+v.toFixed(6));
  return out;
}
function fmtTick(v: number, d: [number, number]) {
  const step = niceStep(d[1] - d[0]);
  return v.toFixed(step >= 1 ? 0 : step >= 0.1 ? 1 : 2);
}
export function refText(lo: number | null, hi: number | null) {
  if (lo != null && hi != null) return `${lo}–${hi}`;
  if (hi != null) return `≤ ${hi}`;
  if (lo != null) return `≥ ${lo}`;
  return "not defined";
}
