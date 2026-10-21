"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { addDays, localDate } from "@/lib/viz";

type Tpl = { id: number; name: string; mapping: { sheet?: string; cells?: Record<string, string>; columns?: Record<string, string>; start_row?: number };
  active: boolean; sheets: string[]; created_at: string };
type Person = { id: number; name: string; active: boolean };

export default function Template() {
  const [tpls, setTpls] = useState<Tpl[]>([]);
  const [fields, setFields] = useState<Record<string, string>>({});
  const [taskFields, setTaskFields] = useState<string[]>([]);
  const [people, setPeople] = useState<Person[]>([]);
  const [sel, setSel] = useState<number | null>(null);
  const [cells, setCells] = useState<Record<string, string>>({});
  const [cols, setCols] = useState<Record<string, string>>({});
  const [sheet, setSheet] = useState("");
  const [startRow, setStartRow] = useState<number | "">("");
  const [who, setWho] = useState<number | "">("");
  const [day, setDay] = useState(addDays(localDate(), -1));
  const [grid, setGrid] = useState<string[][] | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);

  const load = useCallback(async () => {
    const r = await api<{ templates: Tpl[]; fields: Record<string, string>; task_fields: string[] }>("/admin/templates");
    setTpls(r.templates); setFields(r.fields); setTaskFields(r.task_fields);
    setPeople((await api<Person[]>("/admin/people")).filter((p) => p.active));
    return r.templates;
  }, []);
  useEffect(() => { load().then((t) => t[0] && pick(t[0])).catch((e) => setMsg({ ok: false, text: e.message })); }, [load]); // eslint-disable-line react-hooks/exhaustive-deps

  function pick(t: Tpl) {
    setSel(t.id); setSheet(t.mapping.sheet ?? t.sheets[0] ?? ""); setCells(t.mapping.cells ?? {}); setCols(t.mapping.columns ?? {});
    setStartRow(t.mapping.start_row ?? ""); setGrid(null); setMsg(null);
  }
  const mapping = () => ({ sheet, cells: Object.fromEntries(Object.entries(cells).filter(([, v]) => v.trim())),
    columns: Object.fromEntries(Object.entries(cols).filter(([, v]) => v.trim())), ...(startRow !== "" ? { start_row: Number(startRow) } : {}) });

  async function act(fn: () => Promise<unknown>, ok: string) {
    setMsg(null);
    try { await fn(); setMsg({ ok: true, text: ok }); await load(); } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" }); }
  }

  async function upload(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const form = new FormData(formEl);
    const res = await fetch("/api/admin/templates", { method: "POST", body: form, credentials: "same-origin" });
    if (!res.ok) { setMsg({ ok: false, text: (await res.json()).detail ?? "Upload failed" }); return; }
    const t: Tpl = await res.json();
    formEl.reset();
    await load();
    pick(t);
  }

  const current = tpls.find((t) => t.id === sel);

  return (
    <div className="space-y-6">
      <section className="card space-y-3" aria-labelledby="h-upload">
        <h2 id="h-upload" className="text-lg font-semibold">Your company DSR template</h2>
        <p className="text-sm text-muted">Upload the Excel file you use today, then say where each value goes: fixed cells for one-off values
          (name, date) and columns for one row per task. Formulas, formatting and other sheets are kept; charts and pictures inside the
          template are not (a limit of the Excel library).</p>
        <form onSubmit={upload} className="flex flex-wrap items-end gap-2">
          <div className="space-y-1"><label htmlFor="t-name" className="text-sm font-medium">Name</label>
            <input id="t-name" name="name" required defaultValue="Company DSR" className="field" /></div>
          <div className="space-y-1"><label htmlFor="t-file" className="text-sm font-medium">Excel file (.xlsx)</label>
            <input id="t-file" name="file" type="file" required accept=".xlsx" className="field" /></div>
          <button type="submit" className="btn-primary">Upload</button>
        </form>
        {tpls.length > 0 && (
          <div className="flex flex-wrap gap-2">
            {tpls.map((t) => (
              <button key={t.id} onClick={() => pick(t)} aria-pressed={t.id === sel}
                className="btn-secondary aria-pressed:bg-accent aria-pressed:text-accent-fg">{t.name}{t.active ? " (in use)" : ""}</button>
            ))}
          </div>
        )}
      </section>

      {current && (
        <section className="card space-y-4" aria-labelledby="h-map">
          <h2 id="h-map" className="text-lg font-semibold">Map fields: {current.name}</h2>
          <div className="flex flex-wrap gap-4">
            <div className="space-y-1"><label htmlFor="m-sheet" className="text-sm font-medium">Sheet</label>
              <select id="m-sheet" value={sheet} onChange={(e) => setSheet(e.target.value)} className="field w-auto">
                {current.sheets.map((s) => <option key={s}>{s}</option>)}</select></div>
            <div className="space-y-1"><label htmlFor="m-start" className="text-sm font-medium">First task row</label>
              <input id="m-start" type="number" min={1} value={startRow} onChange={(e) => setStartRow(e.target.value ? Number(e.target.value) : "")}
                className="field w-28" placeholder="e.g. 6" /></div>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-muted"><tr><th className="py-1 font-medium">Field</th><th className="font-medium">Fixed cell (e.g. B3)</th>
                <th className="font-medium">Column per task row (e.g. C)</th></tr></thead>
              <tbody className="divide-y divide-line">
                {Object.entries(fields).map(([f, help]) => (
                  <tr key={f}>
                    <td className="py-1.5 pr-3"><span className="font-mono text-xs">{f}</span> <span className="text-xs text-muted">{help}</span></td>
                    <td className="pr-3"><input aria-label={`${f} cell`} value={cells[f] ?? ""} disabled={taskFields.includes(f)}
                      onChange={(e) => setCells({ ...cells, [f]: e.target.value.toUpperCase() })} className="field w-24 py-1 font-mono" /></td>
                    <td><input aria-label={`${f} column`} value={cols[f] ?? ""}
                      onChange={(e) => setCols({ ...cols, [f]: e.target.value.toUpperCase() })} className="field w-20 py-1 font-mono" /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="flex flex-wrap items-end gap-2 border-t border-line pt-4">
            <button className="btn-primary" onClick={() => act(() => api(`/admin/templates/${current.id}/mapping`, { method: "PUT", body: JSON.stringify(mapping()) }), "Mapping saved.")}>Save mapping</button>
            <div className="space-y-1"><label htmlFor="p-who" className="text-sm font-medium">Preview with</label>
              <select id="p-who" value={who} onChange={(e) => setWho(Number(e.target.value))} className="field w-auto">
                <option value="">Choose a person</option>{people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}</select></div>
            <div className="space-y-1"><label htmlFor="p-day" className="text-sm font-medium">Day</label>
              <input id="p-day" type="date" value={day} onChange={(e) => setDay(e.target.value)} className="field" /></div>
            <button className="btn-secondary" disabled={!who} onClick={async () => {
              setMsg(null);
              try {
                const r = await api<{ rows: string[][] }>(`/admin/templates/${current.id}/preview`, { method: "POST",
                  body: JSON.stringify({ user_id: who, day, mapping: mapping() }) });
                setGrid(r.rows);
              } catch (e) { setMsg({ ok: false, text: e instanceof Error ? e.message : "Preview failed" }); }
            }}>Preview</button>
            <button className="btn-secondary" onClick={() => act(() => api(`/admin/templates/${current.id}/activate`, { method: "POST" }), "This template is now used for everyone's 'Company template' export.")}>Use this template</button>
            <button className="btn-secondary text-danger" onClick={() => confirm(`Delete ${current.name}?`) &&
              act(async () => { await api(`/admin/templates/${current.id}`, { method: "DELETE" }); setSel(null); }, "Deleted.")}>Delete</button>
          </div>
          {msg && <p role={msg.ok ? "status" : "alert"} className={`text-sm ${msg.ok ? "text-ok" : "text-danger"}`}>{msg.text}</p>}
          {grid && (
            <div className="overflow-x-auto rounded-lg border border-line">
              <table className="text-xs">
                <tbody>
                  {grid.map((row, i) => (
                    <tr key={i} className="border-b border-line">
                      <th className="bg-bg px-2 py-1 text-muted">{i + 1}</th>
                      {row.map((c, j) => <td key={j} className="max-w-48 truncate border-l border-line px-2 py-1" title={c}>{c}</td>)}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </section>
      )}
      {!current && msg && <p role="alert" className="text-sm text-danger">{msg.text}</p>}
    </div>
  );
}
