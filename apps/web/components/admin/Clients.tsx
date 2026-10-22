"use client";

import { useCallback, useEffect, useState } from "react";

import { api } from "@/lib/api";
import { hm } from "@/lib/viz";

type Ident = { id: number; kind: string; value: string; source: string };
type Client = { id: number; name: string; status: "suggested" | "confirmed" | "ignored"; notes: string; seconds_seen: number; identifiers: Ident[] };
type Settings = { internal_domains: string[]; extra_public_domains: string[]; page_reading: boolean; page_allowlist: string[] };

const KIND: Record<string, string> = { web_domain: "Website", email_domain: "Email domain", email_address: "Email address",
  name_alias: "Name on page", mantis_project: "Mantis project" };

function Chips({ c, onDelete }: { c: Client; onDelete?: (id: number) => void }) {
  return (
    <ul className="flex flex-wrap gap-1.5">
      {c.identifiers.map((i) => (
        <li key={i.id} className="flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-xs">
          <span className="text-muted">{KIND[i.kind] ?? i.kind}:</span> {i.value}
          {onDelete && <button aria-label={`Remove ${i.value}`} onClick={() => onDelete(i.id)} className="ml-0.5 text-muted hover:text-danger">✕</button>}
        </li>
      ))}
      {c.identifiers.length === 0 && <li className="text-xs text-muted">No identifiers yet: add a website or email domain.</li>}
    </ul>
  );
}

export default function Clients() {
  const [clients, setClients] = useState<Client[] | null>(null);
  const [settings, setSettings] = useState<Settings | null>(null);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState("");
  const [filter, setFilter] = useState("");
  const [showIgnored, setShowIgnored] = useState(false);

  const load = useCallback(async () => {
    const [c, s] = await Promise.all([api<Client[]>("/admin/clients"), api<{ clients: Settings }>("/admin/settings")]);
    setClients(c);
    setSettings(s.clients);
  }, []);
  useEffect(() => { load().catch((e) => setMsg({ ok: false, text: e.message })); }, [load]);

  async function act(label: string, fn: () => Promise<unknown>, ok?: (r: unknown) => string) {
    setBusy(label);
    setMsg(null);
    try {
      const r = await fn();
      if (ok) setMsg({ ok: true, text: ok(r) });
      await load();
    } catch (e) {
      setMsg({ ok: false, text: e instanceof Error ? e.message : "Failed" });
    } finally {
      setBusy("");
    }
  }
  const patch = (c: Client, body: object) => act("patch", () => api(`/admin/clients/${c.id}`, { method: "PATCH", body: JSON.stringify(body) }));
  const lines = (v: FormDataEntryValue | null) => String(v || "").split(/[\n,]/).map((x) => x.trim()).filter(Boolean);

  if (!clients || !settings) return <p role="status" className="text-muted">Loading…{msg && <span className="text-danger"> {msg.text}</span>}</p>;

  const confirmed = clients.filter((c) => c.status === "confirmed");
  const suggested = clients.filter((c) => c.status === "suggested");
  const ignored = clients.filter((c) => c.status === "ignored");
  const shown = confirmed.filter((c) => !filter || c.name.toLowerCase().includes(filter.toLowerCase()) ||
    c.identifiers.some((i) => i.value.includes(filter.toLowerCase())));

  return (
    <div className="space-y-6">
      {msg && <p role={msg.ok ? "status" : "alert"} className={`text-sm ${msg.ok ? "text-ok" : "text-danger"}`}>{msg.text}</p>}

      <section className="card space-y-3" aria-labelledby="h-cl-how">
        <h2 id="h-cl-how" className="text-lg font-semibold">How clients are recognised</h2>
        <p className="text-sm text-muted">In order: the club&apos;s website or backoffice address · the club name shown on the page ·
          the Mantis project of a ticket · the email addresses in a thread · the domains of meeting guests. Only
          <b> confirmed</b> clients are used. Your own company domains and public mailboxes (gmail.com…) never count.</p>
        <form onSubmit={(e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          act("settings", () => api("/admin/settings/clients", { method: "PUT", body: JSON.stringify({
            internal_domains: lines(f.get("internal")), extra_public_domains: lines(f.get("public")),
            page_reading: f.get("reading") === "on", page_allowlist: lines(f.get("allow")) }) }), () => "Saved.");
        }} className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1"><label htmlFor="c-int" className="text-sm font-medium">Our company domains</label>
            <textarea id="c-int" name="internal" rows={2} defaultValue={settings.internal_domains.join("\n")} placeholder="globalnorthstar.com" className="field text-sm" />
            <p className="text-xs text-muted">Never treated as a client. One per line.</p></div>
          <div className="space-y-1"><label htmlFor="c-pub" className="text-sm font-medium">Other shared mailbox domains</label>
            <textarea id="c-pub" name="public" rows={2} defaultValue={settings.extra_public_domains.join("\n")} className="field text-sm" />
            <p className="text-xs text-muted">Besides gmail.com, outlook.com and the like.</p></div>
          <label className="flex items-center gap-2 text-sm"><input type="checkbox" name="reading" defaultChecked={settings.page_reading} className="h-4 w-4" />
            Read page headings, menu and club name in the browser (never what people type)</label>
          <div className="space-y-1"><label htmlFor="c-allow" className="text-sm font-medium">Only read pages on these sites (optional)</label>
            <textarea id="c-allow" name="allow" rows={2} defaultValue={settings.page_allowlist.join("\n")} placeholder="Empty = every work site" className="field text-sm" /></div>
          <div className="sm:col-span-2"><button type="submit" className="btn-primary" disabled={!!busy}>Save</button></div>
        </form>
      </section>

      <section className="card space-y-3" aria-labelledby="h-cl-import">
        <h2 id="h-cl-import" className="text-lg font-semibold">Add clubs</h2>
        <div className="grid gap-4 md:grid-cols-2">
          <form onSubmit={(e) => {
            e.preventDefault();
            const formEl = e.currentTarget;
            const text = String(new FormData(formEl).get("text") || "");
            act("import", () => api<{ clubs: number; new: number; identifiers: number }>("/admin/clients/import", { method: "POST", body: JSON.stringify({ text }) }),
              (r) => { const x = r as { clubs: number; new: number; identifiers: number }; formEl.reset(); return `${x.clubs} clubs read, ${x.new} new, ${x.identifiers} websites/emails added.`; });
          }} className="space-y-2">
            <label htmlFor="c-import" className="text-sm font-medium">Paste the club list (e.g. MantisClubs)</label>
            <textarea id="c-import" name="text" rows={5} required className="field font-mono text-xs"
              placeholder={"River Club, riverclub.com\nOak Hills Country Club, oakhills.com, gm@oakhills.com\nLakeside Golf Club"} />
            <p className="text-xs text-muted">One club per line. Optionally add its website or email domains after commas.</p>
            <button type="submit" className="btn-primary" disabled={!!busy}>{busy === "import" ? "Importing…" : "Import"}</button>
          </form>
          <div className="space-y-2">
            <p className="text-sm font-medium">Learn from recent work</p>
            <p className="text-sm text-muted">Looks at the last 14 days: sites with 10+ minutes, club names on pages, email domains
              with 2+ messages and Mantis projects. The AI proposes names; you confirm below. Also runs every night.</p>
            <button className="btn-secondary" disabled={!!busy} onClick={() => act("learn", () => api<Record<string, number>>("/admin/clients/learn", { method: "POST" }),
              (r) => { const x = r as Record<string, number>; const n = Object.values(x).reduce((s, v) => s + v, 0); return n ? `Found ${n} new: ${Object.entries(x).map(([k, v]) => `${v} ${KIND[k] ?? k}`).join(", ")}.` : "Nothing new found."; })}>
              {busy === "learn" ? "Learning… (can take a minute)" : "Learn now"}</button>
            <form onSubmit={(e) => {
              e.preventDefault();
              const formEl = e.currentTarget;
              const name = String(new FormData(formEl).get("name") || "");
              act("add", () => api("/admin/clients", { method: "POST", body: JSON.stringify({ name }) }), () => { formEl.reset(); return `Added ${name}.`; });
            }} className="flex gap-2 pt-2">
              <label htmlFor="c-new" className="sr-only">New client name</label>
              <input id="c-new" name="name" required placeholder="Add one client by name" className="field" />
              <button type="submit" className="btn-secondary" disabled={!!busy}>Add</button>
            </form>
          </div>
        </div>
      </section>

      <section className="card space-y-3" aria-labelledby="h-cl-sug">
        <h2 id="h-cl-sug" className="text-lg font-semibold">Suggested ({suggested.length})</h2>
        {suggested.length === 0 && <p className="text-sm text-muted">Nothing waiting. Suggestions appear as people work on new sites and email new clubs.</p>}
        <ul className="divide-y divide-line">
          {suggested.map((c) => (
            <li key={c.id} className="space-y-2 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <label className="sr-only" htmlFor={`n-${c.id}`}>Name</label>
                <input id={`n-${c.id}`} defaultValue={c.name} className="field w-auto min-w-56 font-medium"
                  onBlur={(e) => e.target.value.trim() && e.target.value !== c.name && patch(c, { name: e.target.value.trim() })} />
                <span className="text-xs text-muted">{c.seconds_seen ? `${hm(c.seconds_seen)} seen` : ""}</span>
                <span className="flex-1" />
                <button className="btn-primary px-3 py-1" disabled={!!busy} onClick={() => patch(c, { status: "confirmed" })}>Confirm</button>
                <label className="sr-only" htmlFor={`m-${c.id}`}>Merge into</label>
                <select id={`m-${c.id}`} className="field w-auto py-1" defaultValue=""
                  onChange={(e) => e.target.value && act("merge", () => api(`/admin/clients/${c.id}/merge`, { method: "POST", body: JSON.stringify({ into_id: Number(e.target.value) }) }), () => `Merged ${c.name}.`)}>
                  <option value="">Same as…</option>
                  {confirmed.map((o) => <option key={o.id} value={o.id}>{o.name}</option>)}
                </select>
                <button className="btn-secondary px-3 py-1" disabled={!!busy} onClick={() => patch(c, { status: "ignored" })}>Not a client</button>
              </div>
              <Chips c={c} />
            </li>
          ))}
        </ul>
      </section>

      <section className="card space-y-3" aria-labelledby="h-cl-conf">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="h-cl-conf" className="text-lg font-semibold">Clients ({confirmed.length})</h2>
          <label className="sr-only" htmlFor="c-filter">Filter clients</label>
          <input id="c-filter" value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter" className="field w-48" />
        </div>
        <ul className="divide-y divide-line">
          {shown.map((c) => (
            <li key={c.id} className="space-y-2 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium">{c.name}</span>
                <span className="flex-1" />
                <form className="flex gap-1" onSubmit={(e) => {
                  e.preventDefault();
                  const formEl = e.currentTarget;
                  const f = new FormData(formEl);
                  act("ident", () => api(`/admin/clients/${c.id}/identifiers`, { method: "POST", body: JSON.stringify({ kind: f.get("kind"), value: f.get("value") }) }), () => { formEl.reset(); return "Added."; });
                }}>
                  <label className="sr-only" htmlFor={`k-${c.id}`}>Kind</label>
                  <select id={`k-${c.id}`} name="kind" className="field w-auto py-1 text-xs">
                    {Object.entries(KIND).map(([k, v]) => <option key={k} value={k}>{v}</option>)}</select>
                  <label className="sr-only" htmlFor={`v-${c.id}`}>Value</label>
                  <input id={`v-${c.id}`} name="value" required placeholder="riverclub.com" className="field w-44 py-1 text-xs" />
                  <button type="submit" className="btn-secondary px-2 py-1 text-xs" disabled={!!busy}>Add</button>
                </form>
                <button className="btn-secondary px-2 py-1 text-xs" disabled={!!busy} onClick={() => patch(c, { status: "ignored" })}>Remove</button>
              </div>
              <Chips c={c} onDelete={(id) => act("del", () => api(`/admin/client-identifiers/${id}`, { method: "DELETE" }))} />
            </li>
          ))}
        </ul>
        {ignored.length > 0 && (
          <div>
            <button className="text-sm text-muted underline-offset-2 hover:underline" onClick={() => setShowIgnored(!showIgnored)}>
              {showIgnored ? "Hide" : "Show"} {ignored.length} marked as not a client</button>
            {showIgnored && <ul className="mt-2 flex flex-wrap gap-2 text-sm">{ignored.map((c) => (
              <li key={c.id}><button className="btn-secondary px-2 py-0.5 text-xs" onClick={() => patch(c, { status: "suggested" })}>{c.name} ↺</button></li>))}</ul>}
          </div>
        )}
      </section>
    </div>
  );
}
