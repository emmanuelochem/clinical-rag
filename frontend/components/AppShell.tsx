"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { Activity, BookOpen, Moon, Stethoscope, Sun, Users, MessagesSquare, ShieldAlert } from "lucide-react";
import { getJSON } from "@/lib/api";

interface Health {
  ollama: { reachable: boolean; missing?: string[] }; reranker: string; chat_model: string; embed_model: string;
  patients: number; kb_documents: number;
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

  const ok = health?.ollama.reachable && !health.ollama.missing?.length;
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
          <div className="flex items-center gap-2 text-xs" title={health ? `Chat: ${health.chat_model} · Embeddings: ${health.embed_model} · Reranker: ${health.reranker}` : "Backend unreachable"}>
            <span className={`h-2 w-2 rounded-full ${!health ? "bg-critical" : ok ? "bg-ok" : "bg-warning"}`} />
            <span className="hidden text-muted lg:inline">
              {!health ? "Backend offline" : !health.ollama.reachable ? "Ollama offline" : health.ollama.missing?.length ? `Missing: ${health.ollama.missing.join(", ")}` : `${health.chat_model}`}
            </span>
          </div>
          <button onClick={toggleTheme} className="rounded-lg p-1.5 text-muted hover:bg-panel-2" aria-label="Toggle theme">
            {theme === "dark" ? <Sun size={16} /> : <Moon size={16} />}
          </button>
        </div>
        <div className="border-t border-line bg-warning-soft px-4 py-1 text-center text-[11.5px] text-warning">
          <ShieldAlert size={12} className="mr-1 inline -mt-0.5" />
          Decision support for clinicians only, not a diagnosis. All patient data shown is synthetic. Models run locally.
        </div>
      </header>
      <main className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-5">{children}</main>
    </div>
  );
}
