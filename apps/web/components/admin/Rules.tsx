"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { hm } from "@/lib/viz";

type Category = { id: number; name: string; klass: string };
type Rule = { id: number; field: string; pattern: string; category_id: number; priority: number; enabled: boolean };
type Suggestion = { id: number; domain: string; category_id: number; reason: string; seconds_seen: number };

const FIELD_HELP: Record<string, string> = {
  domain: "Site, e.g. github.com (also matches subdomains) or *mantis*",
  app: "Program file, e.g. code.exe or excel.exe",
  title: "Pattern in the window or page title",
};
const KLASS_LABEL: Record<string, string> = { productive: "Productive", communication: "Email & chat", meeting: "Meetings",
  neutral: "Neutral", non_work: "Non-work" };

export default function Rules() {
  const [cats, setCats] = useState<Category[]>([]);
  const [rules, setRules] = useState<Rule[]>([]);
  const [sugs, setSugs] = useState<Suggestion[]>([]);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState("");
  const [pick, setPick] = useState<Record<number, number>>({});

  const load = useCallback(async () => {
    try {
      const [c, r, s] = await Promise.all([api<Category[]>("/admin/categories"), api<Rule[]>("/admin/rules"),
        api<Suggestion[]>("/admin/rule-suggestions")]);
      setCats(c); setRules(r); setSugs(s);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load");
    }
  }, []);
  useEffect(() => { load(); }, [load]);
  const catName = (id: number) => cats.find((c) => c.id === id)?.name ?? "?";

  async function act(fn: () => Promise<unknown>) {
    setError("");
    try { await fn(); await load(); } catch (e) { setError(e instanceof Error ? e.message : "Failed"); }
  }

  async function add(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const f = new FormData(formEl);
    await act(() => api("/admin/rules", { method: "POST", body: JSON.stringify({ field: f.get("field"), pattern: f.get("pattern"),
      category_id: Number(f.get("category_id")), priority: Number(f.get("priority") || 0) }) }));
    formEl.reset();
  }

  const shown = rules.filter((r) => !filter || r.pattern.includes(filter.toLowerCase()) || catName(r.category_id).toLowerCase().includes(filter.toLowerCase()));

  return (
    <div className="space-y-6">
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
      <section className="card space-y-3" aria-labelledby="h-sug">
        <h2 id="h-sug" className="text-lg font-semibold">Suggested by AI</h2>
        <p className="text-sm text-muted">Sites with no category that took 10 minutes or more. Nothing is applied until you accept it.</p>
        {sugs.length === 0 && <p className="text-sm text-muted">No suggestions waiting.</p>}
        <ul className="divide-y divide-line">
          {sugs.map((s) => (
            <li key={s.id} className="flex flex-wrap items-center gap-3 py-2 text-sm">
              <span className="min-w-40 font-medium">{s.domain}</span>
              <span className="text-muted">{hm(s.seconds_seen)} seen</span>
              <span className="flex-1 text-muted">{s.reason}</span>
              <label className="sr-only" htmlFor={`sug-${s.id}`}>Category</label>
              <select id={`sug-${s.id}`} className="field w-auto" value={pick[s.id] ?? s.category_id}
                onChange={(e) => setPick({ ...pick, [s.id]: Number(e.target.value) })}>
                {cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
              <button className="btn-primary px-3 py-1" onClick={() => act(() => api(`/admin/rule-suggestions/${s.id}`,
                { method: "POST", body: JSON.stringify({ accept: true, category_id: pick[s.id] ?? s.category_id }) }))}>Accept</button>
              <button className="btn-secondary px-3 py-1" onClick={() => act(() => api(`/admin/rule-suggestions/${s.id}`,
                { method: "POST", body: JSON.stringify({ accept: false }) }))}>Reject</button>
            </li>
          ))}
        </ul>
      </section>

      <section className="card space-y-3" aria-labelledby="h-add-rule">
        <h2 id="h-add-rule" className="text-lg font-semibold">Add a rule</h2>
        <form onSubmit={add} className="grid gap-3 sm:grid-cols-[auto_1fr_auto_auto_auto] sm:items-end">
          <div className="space-y-1"><label htmlFor="r-field" className="text-sm font-medium">Match</label>
            <select id="r-field" name="field" className="field">{Object.keys(FIELD_HELP).map((f) => <option key={f} value={f}>{f}</option>)}</select></div>
          <div className="space-y-1"><label htmlFor="r-pattern" className="text-sm font-medium">Pattern</label>
            <input id="r-pattern" name="pattern" required placeholder="github.com" className="field" /></div>
          <div className="space-y-1"><label htmlFor="r-cat" className="text-sm font-medium">Category</label>
            <select id="r-cat" name="category_id" className="field">{cats.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}</select></div>
          <div className="space-y-1"><label htmlFor="r-pri" className="text-sm font-medium">Priority</label>
            <input id="r-pri" name="priority" type="number" defaultValue={0} className="field w-24" /></div>
          <button type="submit" className="btn-primary">Add rule</button>
        </form>
        <p className="text-xs text-muted">{Object.entries(FIELD_HELP).map(([k, v]) => `${k}: ${v}`).join(" · ")}. Higher priority wins; at equal priority a site rule beats a title rule beats a program rule.</p>
      </section>

      <section className="card space-y-3" aria-labelledby="h-rules">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="h-rules" className="text-lg font-semibold">Rules ({rules.length})</h2>
          <label className="sr-only" htmlFor="r-filter">Filter rules</label>
          <input id="r-filter" placeholder="Filter" value={filter} onChange={(e) => setFilter(e.target.value)} className="field w-48" />
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-left text-sm">
            <thead className="text-muted"><tr><th className="py-1 font-medium">Match</th><th className="font-medium">Pattern</th>
              <th className="font-medium">Category</th><th className="font-medium">Priority</th><th className="font-medium">On</th><th /></tr></thead>
            <tbody className="divide-y divide-line">
              {shown.map((r) => (
                <tr key={r.id}>
                  <td className="py-1.5">{r.field}</td>
                  <td className="font-mono text-xs">{r.pattern}</td>
                  <td>{catName(r.category_id)} <span className="text-xs text-muted">{KLASS_LABEL[cats.find((c) => c.id === r.category_id)?.klass ?? ""]}</span></td>
                  <td>{r.priority}</td>
                  <td><input type="checkbox" checked={r.enabled} aria-label={`Rule ${r.pattern} enabled`} className="h-4 w-4"
                    onChange={(e) => act(() => api(`/admin/rules/${r.id}`, { method: "PUT", body: JSON.stringify({ ...r, enabled: e.target.checked }) }))} /></td>
                  <td className="text-right"><button className="btn-secondary px-2 py-0.5 text-xs"
                    onClick={() => confirm(`Delete the rule for ${r.pattern}?`) && act(() => api(`/admin/rules/${r.id}`, { method: "DELETE" }))}>Delete</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted">Rule changes apply when a day is next rebuilt (every 5 minutes for today; open any past day to rebuild it).</p>
      </section>
    </div>
  );
}
