"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Activity, BookOpen, Moon, Stethoscope, Sun, Users, MessagesSquare, ShieldAlert } from "lucide-react";
import { getJSON } from "@/lib/api";

interface Health {
  llm: {
    provider: string; label: string; chat_model: string; planner_model: string; key_configured: boolean;
    key_hint: string | null; reachable: boolean; missing: string[]; error: string | null;
  };
  embeddings: { provider: string; model: string; index_mismatch: string | null };
  reranker: string; chat_model: string; embed_model: string; patients: number; kb_documents: number;
}

function status(h: Health | null): { tone: "ok" | "warn" | "bad"; text: string } {
  if (!h) return { tone: "bad", text: "Backend offline" };
  if (h.embeddings.index_mismatch) return { tone: "bad", text: "Re-index needed" };
  if (!h.llm.key_configured) return { tone: "warn", text: `${h.llm.label} API key missing` };
  if (!h.llm.reachable) return { tone: "warn", text: `${h.llm.label} unreachable` };
  if (h.llm.missing.length) return { tone: "warn", text: `Model not available: ${h.llm.missing.join(", ")}` };
  return { tone: "ok", text: `${h.llm.label} · ${h.llm.chat_model}` };
}

const NAV = [
  { href: "/", label: "Patients", icon: Users },
  { href: "/cohort", label: "Cohort", icon: Activity },
  { href: "/assistant", label: "Reference Q&A", icon: MessagesSquare },
  { href: "/knowledge", label: "Knowledge base", icon: BookOpen },
];

export function AppShell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const [health, setHealth] = useState<Health | null>(null);
  const [theme, setTheme] = useState<"light" | "dark" | null>(null);

  useEffect(() => {
    try {
      const t = localStorage.getItem("theme") as "light" | "dark" | null;
      if (t) { document.documentElement.dataset.theme = t; setTheme(t); }
    } catch { /* storage unavailable */ }
    const load = () => getJSON<Health>("/api/health").then(setHealth).catch(() => setHealth(null));
    load();
    const id = setInterval(load, 30000);
    return () => clearInterval(id);
  }, []);

  const toggleTheme = () => {
    const isDark = theme ? theme === "dark" : window.matchMedia("(prefers-color-scheme: dark)").matches;
    const next = isDark ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    setTheme(next);
    try { localStorage.setItem("theme", next); } catch { /* ignore */ }
  };

  const st = status(health);
  const setup = health && (!health.llm.key_configured || health.embeddings.index_mismatch || (health.llm.reachable && health.llm.missing.length > 0));
  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-30 border-b border-line bg-panel/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1500px] items-center gap-4 px-4 py-2.5">
          <Link href="/" className="flex items-center gap-2 font-semibold">
            <span className="grid h-7 w-7 place-items-center rounded-lg bg-accent text-white dark:text-black"><Stethoscope size={16} /></span>
            <span className="hidden sm:inline">Clinical RAG</span>
          </Link>
          <nav className="flex min-w-0 flex-1 items-center gap-1 overflow-x-auto">
            {NAV.map(({ href, label, icon: Icon }) => {
              const active = href === "/" ? path === "/" || path.startsWith("/patients") : path.startsWith(href);
              return (
                <Link key={href} href={href}
                  className={`flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm ${active ? "bg-accent-soft font-medium text-accent" : "text-muted hover:bg-panel-2 hover:text-fg"}`}>
                  <Icon size={15} /><span className="hidden md:inline">{label}</span>
                </Link>
              );
            })}
          </nav>
          <div className="flex min-w-0 items-center gap-2 text-xs"
            title={health ? `Chat: ${health.llm.label} ${health.llm.chat_model} (planner ${health.llm.planner_model}) · Embeddings: ${health.embeddings.model} (${health.embeddings.provider}) · Reranker: ${health.reranker}${health.llm.error ? `\n${health.llm.error}` : ""}` : "Backend unreachable"}>
            <span className={`h-2 w-2 shrink-0 rounded-full ${st.tone === "bad" ? "bg-critical" : st.tone === "ok" ? "bg-ok" : "bg-warning"}`} />
            <span className="hidden truncate text-muted lg:inline">{st.text}</span>
          </div>
          <button onClick={toggleTheme} className="rounded-lg p-1.5 text-muted hover:bg-panel-2" aria-label="Toggle theme">
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>
        </div>
        <div className="border-t border-line bg-warning-soft px-4 py-1 text-center text-[11.5px] text-warning">
          <ShieldAlert size={12} className="mr-1 inline -mt-0.5" />
          Decision support for clinicians only, not a diagnosis. All patient data shown is synthetic.
        </div>
        {setup && health && (
          <div className="border-t border-line bg-info-soft px-4 py-2 text-[13px] text-info">
            <div className="mx-auto max-w-[1500px]">
              {health.embeddings.index_mismatch ? (
                <><b>Search index needs rebuilding.</b> {health.embeddings.index_mismatch}</>
              ) : !health.llm.key_configured ? (
                <><b>Add a free {health.llm.label} API key to enable the assistant and differentials.</b>{" "}
                  Put <code className="rounded bg-panel px-1">{health.llm.key_hint?.split(" ")[0]}=…</code> in <code className="rounded bg-panel px-1">.env</code>, then restart the backend.
                  {health.llm.key_hint?.includes("http") && <> Get one at{" "}
                    <a className="underline" href={health.llm.key_hint.match(/https?:\/\/[^\s)]+/)?.[0]} target="_blank" rel="noreferrer">{health.llm.key_hint.match(/https?:\/\/[^\s)]+/)?.[0]}</a>.</>}
                  {" "}Patient records, charts and search work without it.</>
              ) : (
                <><b>Model not available on {health.llm.label}:</b> {health.llm.missing.join(", ")}. Set <code className="rounded bg-panel px-1">RAG_CHAT_MODEL</code> / <code className="rounded bg-panel px-1">RAG_PLANNER_MODEL</code> in .env to a current model ID.</>
              )}
            </div>
          </div>
        )}
      </header>
      <main className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-5">{children}</main>
    </div>
  );
}
