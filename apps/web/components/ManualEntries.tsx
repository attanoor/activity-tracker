"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { clock, hm } from "@/lib/viz";

type Entry = { id: number; start: string; end: string; kind: string; title: string; client: string | null; note: string };
const KINDS: Record<string, string> = { call: "Phone call", site_visit: "Site visit", meeting: "Meeting", other: "Other work" };

/** Work the tracker could not see (calls and visits away from the PC), logged by the person themselves. */
export default function ManualEntries({ day, tz, onChange }: { day: string; tz: string; onChange: () => void }) {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [editable, setEditable] = useState(true);
  const [reason, setReason] = useState("");
  const [clients, setClients] = useState<{ id: number; name: string }[]>([]);
  const [error, setError] = useState("");
  const [open, setOpen] = useState(false);

  const load = useCallback(async () => {
    const r = await api<{ entries: Entry[]; editable: boolean; reason: string }>(`/me/manual-entries?day=${day}`);
    setEntries(r.entries); setEditable(r.editable); setReason(r.reason);
  }, [day]);
  useEffect(() => { load().catch(() => undefined); api<{ id: number; name: string }[]>("/clients").then(setClients).catch(() => undefined); }, [load]);

  async function add(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const f = new FormData(formEl);
    setError("");
    try {
      await api("/me/manual-entries", { method: "POST", body: JSON.stringify({ day, start: f.get("start"), end: f.get("end"),
        kind: f.get("kind"), title: f.get("title"), client_id: f.get("client") ? Number(f.get("client")) : null, note: f.get("note") }) });
      formEl.reset();
      setOpen(false);
      await load();
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add");
    }
  }

  return (
    <div className="space-y-3">
      {entries.length === 0 && <p className="text-sm text-muted">Nothing logged. Add calls or visits the tracker could not see, so they count in your day.</p>}
      <ul className="divide-y divide-line">
        {entries.map((m) => (
          <li key={m.id} className="flex flex-wrap items-center gap-2 py-2 text-sm">
            <span className="tabular-nums text-muted">{clock(m.start, tz)}–{clock(m.end, tz)}</span>
            <span className="font-medium">{m.title}</span>
            <span className="text-xs text-muted">{KINDS[m.kind]}{m.client ? ` · ${m.client}` : ""} · {hm((new Date(m.end).getTime() - new Date(m.start).getTime()) / 1000)}</span>
            {editable && <button className="btn-secondary ml-auto px-2 py-0.5 text-xs" aria-label={`Remove ${m.title}`}
              onClick={async () => { await api(`/me/manual-entries/${m.id}`, { method: "DELETE" }); await load(); onChange(); }}>Remove</button>}
          </li>
        ))}
      </ul>
      {!editable && <p className="text-sm text-muted">{reason}</p>}
      {editable && !open && <button className="btn-secondary" onClick={() => setOpen(true)}>Log work away from the PC</button>}
      {editable && open && (
        <form onSubmit={add} className="grid gap-3 rounded-lg border border-line p-3 sm:grid-cols-6">
          <div className="space-y-1 sm:col-span-1"><label htmlFor="me-start" className="text-xs font-medium">From</label>
            <input id="me-start" name="start" type="time" required className="field" /></div>
          <div className="space-y-1 sm:col-span-1"><label htmlFor="me-end" className="text-xs font-medium">To</label>
            <input id="me-end" name="end" type="time" required className="field" /></div>
          <div className="space-y-1 sm:col-span-2"><label htmlFor="me-kind" className="text-xs font-medium">What</label>
            <select id="me-kind" name="kind" className="field">{Object.entries(KINDS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select></div>
          <div className="space-y-1 sm:col-span-2"><label htmlFor="me-client" className="text-xs font-medium">Client</label>
            <select id="me-client" name="client" className="field"><option value="">None / internal</option>
              {clients.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
          <div className="space-y-1 sm:col-span-3"><label htmlFor="me-title" className="text-xs font-medium">Title</label>
            <input id="me-title" name="title" required maxLength={200} placeholder="On-site POS training" className="field" /></div>
          <div className="space-y-1 sm:col-span-3"><label htmlFor="me-note" className="text-xs font-medium">Note (optional)</label>
            <input id="me-note" name="note" maxLength={1000} className="field" /></div>
          {error && <p role="alert" className="text-sm text-danger sm:col-span-6">{error}</p>}
          <div className="flex gap-2 sm:col-span-6">
            <button type="submit" className="btn-primary">Add</button>
            <button type="button" className="btn-secondary" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </form>
      )}
    </div>
  );
}
