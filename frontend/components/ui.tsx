import type { Alert, Flag } from "@/lib/types";
import { AlertOctagon, AlertTriangle, Info } from "lucide-react";
import { flagLabel } from "@/lib/api";

export function FlagBadge({ flag }: { flag: Flag | string }) {
  if (flag === "N") return null;
  const crit = flag === "HH" || flag === "LL";
  return (
    <span title={flagLabel[flag]}
      className={`ml-1.5 inline-flex rounded px-1 text-[10.5px] font-bold ${crit ? "bg-critical text-white" : "bg-warning-soft text-warning"}`}>
      {flag}
    </span>
  );
}

export function AlertsBanner({ alerts, compact = false }: { alerts: Alert[]; compact?: boolean }) {
  if (!alerts.length) return null;
  return (
    <div className="space-y-1.5">
      {alerts.map((a, i) => {
        const Icon = a.severity === "critical" ? AlertOctagon : a.severity === "warning" ? AlertTriangle : Info;
        const tone = a.severity === "critical" ? "border-critical/30 bg-critical-soft text-critical"
          : a.severity === "warning" ? "border-warning/30 bg-warning-soft text-warning" : "border-info/30 bg-info-soft text-info";
        return (
          <div key={i} className={`flex gap-2 rounded-lg border px-3 py-2 text-sm ${tone}`}>
            <Icon size={16} className="mt-0.5 shrink-0" />
            <div className="min-w-0">
              <span className="font-semibold">{a.title}</span>
              {!compact && <span className="text-fg/80"> — {a.detail}</span>}
              {!compact && a.evidence.length > 0 && (
                <div className="mt-0.5 text-xs text-fg/60">Evidence: {a.evidence.join(" · ")}</div>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return <div className="rounded-lg border border-dashed border-line px-4 py-8 text-center text-sm text-muted">{children}</div>;
}

export function Spinner({ size = 14 }: { size?: number }) {
  return <span style={{ width: size, height: size }} className="inline-block animate-spin rounded-full border-2 border-accent border-t-transparent" />;
}
