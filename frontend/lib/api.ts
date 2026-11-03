import type { AgentEvent } from "./types";

export async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(path, { cache: "no-store" });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

export async function sendJSON<T>(path: string, body: unknown, method = "POST"): Promise<T> {
  const r = await fetch(path, { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
  return r.json();
}

/** POST a JSON body and iterate over the server-sent events it streams back. */
export async function* streamEvents(path: string, body: unknown, signal?: AbortSignal): AsyncGenerator<AgentEvent> {
  const r = await fetch(path, {
    method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
    body: JSON.stringify(body), signal,
  });
  if (!r.ok || !r.body) {
    yield { type: "error", message: `${r.status}: ${await r.text()}` };
    return;
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let idx;
    while ((idx = buf.indexOf("\n\n")) !== -1) {
      const frame = buf.slice(0, idx);
      buf = buf.slice(idx + 2);
      for (const line of frame.split("\n")) {
        if (line.startsWith("data: ")) {
          try { yield JSON.parse(line.slice(6)) as AgentEvent; } catch { /* ignore malformed frame */ }
        }
      }
    }
  }
}

export const fmtDate = (d?: string | null) =>
  d ? new Date(d + (d.length === 10 ? "T00:00:00" : "")).toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" }) : "—";

export const flagLabel: Record<string, string> = { N: "Normal", H: "High", L: "Low", HH: "Critical high", LL: "Critical low" };
