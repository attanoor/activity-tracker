"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";

type Summary = { content: { summary: string; trends?: string[]; risks?: string[]; suggestions?: string[]; ai_status: string; days?: number };
  generated_at: string; start: string } | null;

/** An AI summary for a week or month (person or team), loaded if it exists, generated on request. */
export default function PeriodSummary({ base, period, start }: { base: string; period: "week" | "month"; start: string }) {
  const [s, setS] = useState<Summary | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const url = `${base}/period/${period}/${start}`;

  useEffect(() => {
    setS(undefined);
    api<Summary>(url).then(setS).catch(() => setS(null));
  }, [url]);

  async function generate() {
    setBusy(true);
    setError("");
    try {
      setS(await api<Summary>(url, { method: "POST" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not generate");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="font-medium capitalize">{period} summary</p>
        <button onClick={generate} disabled={busy} className="btn-secondary px-3 py-1 text-sm">
          {busy ? "Writing…" : s ? "Regenerate" : "Generate"}
        </button>
      </div>
      {s === undefined && <p className="text-sm text-muted" role="status">Loading…</p>}
      {s === null && <p className="text-sm text-muted">Not written yet. It is generated automatically at the start of each {period}.</p>}
      {s && (
        <div className="space-y-2 text-sm">
          <p>{s.content.summary}</p>
          {(["trends", "risks", "suggestions"] as const).map((k) => s.content[k]?.length ? (
            <div key={k}><p className="text-xs uppercase tracking-wide text-muted">{k}</p>
              <ul className="list-disc pl-5">{s.content[k]!.map((x) => <li key={x}>{x}</li>)}</ul></div>) : null)}
          <p className="text-xs text-muted">From {s.start} · {s.content.ai_status === "fallback" ? "written by the tracker (AI unavailable)" : "written by AI"} · {new Date(s.generated_at).toLocaleString()}</p>
        </div>
      )}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </div>
  );
}
