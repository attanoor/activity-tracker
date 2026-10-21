"use client";

import { useEffect, useState } from "react";

import { api } from "@/lib/api";
import { localDate } from "@/lib/viz";

type Settings = {
  ai: { enabled: boolean; ollama_url: string; model: string; timeout_s: number };
  email: { enabled: boolean; host: string; port: number; starttls: boolean; username: string; from_addr: string; send_time: string;
    send_unreviewed: boolean; attach_excel: boolean; attach_pdf: boolean; password_set: boolean };
  google: { mode: string; client_id: string; redirect_base: string; calendar: boolean; gmail: boolean; drive: boolean;
    show_subjects_to_managers: boolean; client_secret_set: boolean; service_account_json_set: boolean };
  mantis: { enabled: boolean; base_url: string; token_set: boolean; token_env: string };
  tracking: { retention_days: number; generate_after_shift_minutes: number; privacy_text: string };
  excel: { shared_folder: string; master_enabled: boolean };
};

function Section({ title, children, intro }: { title: string; intro?: React.ReactNode; children: React.ReactNode }) {
  const id = `h-${title.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <section className="card space-y-4" aria-labelledby={id}>
      <div><h2 id={id} className="text-lg font-semibold">{title}</h2>{intro && <div className="mt-1 text-sm text-muted">{intro}</div>}</div>
      {children}
    </section>
  );
}

function F({ id, label, hint, children }: { id: string; label: string; hint?: string; children: React.ReactNode }) {
  return <div className="space-y-1"><label htmlFor={id} className="text-sm font-medium">{label}</label>{children}
    {hint && <p className="text-xs text-muted">{hint}</p>}</div>;
}

function Check({ name, label, checked }: { name: string; label: string; checked: boolean }) {
  return <label className="flex items-center gap-2 text-sm"><input type="checkbox" name={name} defaultChecked={checked} className="h-4 w-4" />{label}</label>;
}

export default function Integrations() {
  const [s, setS] = useState<Settings | null>(null);
  const [msg, setMsg] = useState<Record<string, { ok: boolean; text: string }>>({});
  const [syncOut, setSyncOut] = useState("");

  const load = () => api<Settings>("/admin/settings").then(setS).catch((e) => setMsg({ load: { ok: false, text: e.message } }));
  useEffect(() => { load(); }, []);

  function save(section: keyof Settings, transform: (f: FormData) => Record<string, unknown>) {
    return async (e: React.FormEvent<HTMLFormElement>) => {
      e.preventDefault();
      const f = new FormData(e.currentTarget);
      try {
        await api(`/admin/settings/${section}`, { method: "PUT", body: JSON.stringify(transform(f)) });
        setMsg({ ...msg, [section]: { ok: true, text: "Saved." } });
        load();
      } catch (err) {
        setMsg({ ...msg, [section]: { ok: false, text: err instanceof Error ? err.message : "Could not save" } });
      }
    };
  }
  const on = (f: FormData, k: string) => f.get(k) === "on";
  const Msg = ({ k }: { k: string }) => msg[k] ? <p role={msg[k].ok ? "status" : "alert"} className={`text-sm ${msg[k].ok ? "text-ok" : "text-danger"}`}>{msg[k].text}</p> : null;

  async function test(k: string, path: string, body?: object) {
    setMsg({ ...msg, [k]: { ok: true, text: "Testing…" } });
    try {
      const r = await api<Record<string, unknown>>(path, { method: "POST", body: body ? JSON.stringify(body) : undefined });
      setMsg({ ...msg, [k]: { ok: true, text: k === "ai" ? `Model ${r.model} answered in ${r.seconds}s.` : "Test email sent." } });
    } catch (e) {
      setMsg({ ...msg, [k]: { ok: false, text: e instanceof Error ? e.message : "Test failed" } });
    }
  }

  async function readFile(input: HTMLInputElement | null): Promise<string> {
    const file = input?.files?.[0];
    return file ? await file.text() : "";
  }

  if (!s) return <p role="status" className="text-muted">Loading…<Msg k="load" /></p>;

  return (
    <div className="space-y-6">
      <Section title="AI model" intro="Runs locally through Ollama, so activity never leaves your network.">
        <form onSubmit={save("ai", (f) => ({ enabled: on(f, "enabled"), ollama_url: f.get("ollama_url"), model: f.get("model"),
          timeout_s: Number(f.get("timeout_s")) }))} className="grid gap-4 sm:grid-cols-2">
          <Check name="enabled" label="Use AI to write reports and summaries" checked={s.ai.enabled} />
          <div />
          <F id="ai-url" label="Ollama address"><input id="ai-url" name="ollama_url" defaultValue={s.ai.ollama_url} className="field" /></F>
          <F id="ai-model" label="Model" hint="mistral-nemo:12b fits the 11 GB GPU."><input id="ai-model" name="model" defaultValue={s.ai.model} className="field" /></F>
          <F id="ai-timeout" label="Timeout per call (seconds)"><input id="ai-timeout" name="timeout_s" type="number" min={30} max={1200} defaultValue={s.ai.timeout_s} className="field" /></F>
          <div className="flex items-end gap-2 sm:col-span-2">
            <button type="submit" className="btn-primary">Save</button>
            <button type="button" className="btn-secondary" onClick={() => test("ai", "/admin/settings/ai/test")}>Test the model</button>
          </div>
        </form>
        <Msg k="ai" />
      </Section>

      <Section title="Google: Calendar, Gmail, Drive" intro={<>
        Read-only. Gmail is read as headers only (never message bodies).
        <b> Service account</b> (Google Workspace, recommended): one key with domain-wide delegation, nobody has to connect.
        <b> Per-person</b>: each person connects on their Account page; Google requires this site on https for that.</>}>
        <form onSubmit={async (e) => {
          e.preventDefault();
          const formEl = e.currentTarget;
          const f = new FormData(formEl);
          const key = await readFile(formEl.querySelector<HTMLInputElement>("#g-key"));
          await save("google", () => ({ mode: f.get("mode"), client_id: f.get("client_id"), redirect_base: f.get("redirect_base"),
            calendar: on(f, "calendar"), gmail: on(f, "gmail"), drive: on(f, "drive"),
            show_subjects_to_managers: on(f, "show_subjects_to_managers"),
            client_secret: f.get("client_secret") || "", service_account_json: key }))(e);
        }} className="grid gap-4 sm:grid-cols-2">
          <F id="g-mode" label="Connection">
            <select id="g-mode" name="mode" defaultValue={s.google.mode} className="field">
              <option value="off">Off</option><option value="service_account">Service account (Workspace)</option><option value="oauth">Each person connects</option>
            </select>
          </F>
          <div className="flex flex-wrap items-end gap-4">
            <Check name="calendar" label="Calendar" checked={s.google.calendar} />
            <Check name="gmail" label="Gmail counts" checked={s.google.gmail} />
            <Check name="drive" label="Drive activity" checked={s.google.drive} />
          </div>
          <F id="g-key" label={`Service-account key (.json) ${s.google.service_account_json_set ? "· a key is saved" : ""}`}
            hint="In Google Admin, allow its client ID the scopes calendar.readonly, gmail.metadata, drive.activity.readonly.">
            <input id="g-key" type="file" accept="application/json,.json" className="field" />
          </F>
          <div />
          <F id="g-client" label="OAuth client ID (per-person mode)"><input id="g-client" name="client_id" defaultValue={s.google.client_id} className="field" /></F>
          <F id="g-secret" label={`OAuth client secret ${s.google.client_secret_set ? "· saved (leave empty to keep)" : ""}`}>
            <input id="g-secret" name="client_secret" type="password" autoComplete="off" className="field" /></F>
          <F id="g-redirect" label="Site address for sign-in" hint="https address of this site; the redirect is <address>/api/integrations/google/callback">
            <input id="g-redirect" name="redirect_base" defaultValue={s.google.redirect_base} placeholder="https://tracker.example.com" className="field" /></F>
          <div className="flex items-end"><Check name="show_subjects_to_managers" label="Managers may see email subjects" checked={s.google.show_subjects_to_managers} /></div>
          <div className="sm:col-span-2"><button type="submit" className="btn-primary">Save</button></div>
        </form>
        <Msg k="google" />
      </Section>

      <Section title="MantisBT" intro={<>Every ticket action (reported, responded, assigned, resolved, reopened, attached) is credited to the person who did it.
        The API token is read from the <code className="font-mono">{s.mantis.token_env}</code> environment variable on the server,
        never stored here: {s.mantis.token_set ? <b className="text-ok">token found</b> : <b className="text-danger">not set yet</b>}.
        People are matched by their Mantis username (Admin → People → Edit), else by email.</>}>
        <form onSubmit={save("mantis", (f) => ({ enabled: on(f, "enabled"), base_url: f.get("base_url") }))} className="grid gap-4 sm:grid-cols-2">
          <F id="m-url" label="Mantis address"><input id="m-url" name="base_url" defaultValue={s.mantis.base_url} placeholder="https://mantis.example.com" className="field" /></F>
          <div className="flex items-end"><Check name="enabled" label="Sync Mantis" checked={s.mantis.enabled} /></div>
          <div className="sm:col-span-2"><button type="submit" className="btn-primary">Save</button></div>
        </form>
        <Msg k="mantis" />
      </Section>

      <Section title="End-of-day email" intro="Each report goes to the person's team manager with a copy to the person, plus a team digest.">
        <form onSubmit={save("email", (f) => ({ enabled: on(f, "enabled"), host: f.get("host"), port: Number(f.get("port")),
          starttls: on(f, "starttls"), username: f.get("username"), password: f.get("password") || "", from_addr: f.get("from_addr"),
          send_time: f.get("send_time"), send_unreviewed: on(f, "send_unreviewed"), attach_excel: on(f, "attach_excel"),
          attach_pdf: on(f, "attach_pdf") }))} className="grid gap-4 sm:grid-cols-2">
          <Check name="enabled" label="Send emails" checked={s.email.enabled} />
          <Check name="starttls" label="Use STARTTLS" checked={s.email.starttls} />
          <F id="e-host" label="SMTP server"><input id="e-host" name="host" defaultValue={s.email.host} className="field" /></F>
          <F id="e-port" label="Port"><input id="e-port" name="port" type="number" defaultValue={s.email.port} className="field" /></F>
          <F id="e-user" label="Username"><input id="e-user" name="username" defaultValue={s.email.username} autoComplete="off" className="field" /></F>
          <F id="e-pass" label={`Password ${s.email.password_set ? "· saved (leave empty to keep)" : ""}`}>
            <input id="e-pass" name="password" type="password" autoComplete="new-password" className="field" /></F>
          <F id="e-from" label="From address"><input id="e-from" name="from_addr" type="email" defaultValue={s.email.from_addr} className="field" /></F>
          <F id="e-time" label="Send at (team's local time)"><input id="e-time" name="send_time" type="time" defaultValue={s.email.send_time} className="field" /></F>
          <Check name="send_unreviewed" label="Send drafts not submitted by then, marked 'not reviewed'" checked={s.email.send_unreviewed} />
          <div className="flex gap-4"><Check name="attach_excel" label="Attach Excel" checked={s.email.attach_excel} />
            <Check name="attach_pdf" label="Attach PDF" checked={s.email.attach_pdf} /></div>
          <div className="flex flex-wrap items-end gap-2 sm:col-span-2">
            <button type="submit" className="btn-primary">Save</button>
            <input id="e-test" placeholder="Send a test to…" type="email" className="field w-64" aria-label="Test email address" />
            <button type="button" className="btn-secondary" onClick={() => test("email", "/admin/settings/email/test",
              { to: (document.getElementById("e-test") as HTMLInputElement).value })}>Send test</button>
          </div>
        </form>
        <Msg k="email" />
      </Section>

      <Section title="Reports and data">
        <form onSubmit={save("tracking", (f) => ({ retention_days: Number(f.get("retention_days")),
          generate_after_shift_minutes: Number(f.get("generate_after_shift_minutes")), privacy_text: f.get("privacy_text") }))}
          className="grid gap-4 sm:grid-cols-2">
          <F id="t-gen" label="Draft the report this many minutes after the shift ends">
            <input id="t-gen" name="generate_after_shift_minutes" type="number" min={0} max={240} defaultValue={s.tracking.generate_after_shift_minutes} className="field" /></F>
          <F id="t-ret" label="Keep raw activity for (days)" hint="Sessions, analyses and reports are kept.">
            <input id="t-ret" name="retention_days" type="number" min={7} max={365} defaultValue={s.tracking.retention_days} className="field" /></F>
          <div className="sm:col-span-2"><F id="t-priv" label="Privacy notice (shown on the Downloads page)">
            <textarea id="t-priv" name="privacy_text" rows={3} defaultValue={s.tracking.privacy_text} className="field" /></F></div>
          <div className="sm:col-span-2"><button type="submit" className="btn-primary">Save</button></div>
        </form>
        <Msg k="tracking" />
        <form onSubmit={save("excel", (f) => ({ shared_folder: f.get("shared_folder"), master_enabled: on(f, "master_enabled") }))}
          className="grid gap-4 border-t border-line pt-4 sm:grid-cols-2">
          <F id="x-folder" label="Shared folder for daily Excel files" hint="A folder this server can write to, e.g. \\fileserver\DSR. Leave empty for none.">
            <input id="x-folder" name="shared_folder" defaultValue={s.excel.shared_folder} className="field" /></F>
          <div className="flex items-end"><Check name="master_enabled" label="Keep a master workbook per team (one sheet per month)" checked={s.excel.master_enabled} /></div>
          <div className="sm:col-span-2"><button type="submit" className="btn-primary">Save</button></div>
        </form>
        <Msg k="excel" />
      </Section>

      <Section title="Sync now" intro="Runs Mantis and Google for a day straight away (normally every 30 minutes).">
        <form onSubmit={async (e) => {
          e.preventDefault();
          const f = new FormData(e.currentTarget);
          setSyncOut("Syncing…");
          try {
            const r = await api("/admin/sync", { method: "POST", body: JSON.stringify({ day: f.get("day") }) });
            setSyncOut(JSON.stringify(r, null, 2));
          } catch (err) { setSyncOut(err instanceof Error ? err.message : "Failed"); }
        }} className="flex flex-wrap items-end gap-2">
          <F id="s-day" label="Day"><input id="s-day" name="day" type="date" defaultValue={localDate()} className="field" /></F>
          <button type="submit" className="btn-secondary">Sync</button>
        </form>
        {syncOut && <pre className="overflow-x-auto rounded-lg bg-bg p-3 text-xs">{syncOut}</pre>}
      </Section>
    </div>
  );
}
