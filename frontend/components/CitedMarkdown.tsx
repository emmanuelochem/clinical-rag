"use client";

import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { Source } from "@/lib/types";

const KIND_TONE: Record<string, string> = {
  record: "bg-accent-soft text-accent border-accent/30",
  note: "bg-info-soft text-info border-info/30",
  kb: "bg-panel-2 text-fg border-line",
};

export function CitationChip({ n, source, onOpen }: { n: number; source?: Source; onOpen: (n: number) => void }) {
  return (
    <button type="button" onClick={() => onOpen(n)} title={source ? `${source.title}` : `Source ${n}`}
      className={`mx-0.5 inline-flex h-[18px] min-w-[18px] -translate-y-px items-center justify-center rounded border px-1 align-middle text-[10.5px] font-semibold hover:brightness-95 ${KIND_TONE[source?.kind ?? "kb"]}`}>
      {n}
    </button>
  );
}

/** Renders Markdown, turning [n] citation markers into clickable chips linked to sources. */
export function CitedMarkdown({ text, sources, onOpen, streaming }: {
  text: string; sources: Source[]; onOpen: (n: number) => void; streaming?: boolean;
}) {
  const linked = text.replace(/\[(\d+(?:\s*,\s*\d+)*)\](?!\()/g, (_, g: string) =>
    g.split(",").map((x) => `[${x.trim()}](#cite-${x.trim()})`).join(""));
  return (
    <div className={`prose-clin ${streaming ? "caret" : ""}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]}
        components={{
          a: ({ href, children }) => {
            if (href?.startsWith("#cite-")) {
              const n = Number(href.slice(6));
              return <CitationChip n={n} source={sources.find((s) => s.n === n)} onOpen={onOpen} />;
            }
            return <a href={href} target="_blank" rel="noreferrer" className="text-accent underline">{children}</a>;
          },
        }}>
        {linked}
      </ReactMarkdown>
    </div>
  );
}
