"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useMemo, useState } from "react";

import CopyField from "@/components/CopyField";
import Clients from "@/components/admin/Clients";
import Integrations from "@/components/admin/Integrations";
import Rules from "@/components/admin/Rules";
import Template from "@/components/admin/Template";
import Modal from "@/components/Modal";
import Shell, { useUser } from "@/components/Shell";
import { api } from "@/lib/api";

type Team = { id: number; name: string; timezone: string; shift_start: string; shift_end: string; break_minutes: number; manager_id: number | null };
type Person = { id: number; email: string; name: string; role: string; team_id: number | null; timezone: string | null;
  active: boolean; devices: number; last_seen_at: string | null; mantis_username: string | null; google_email: string | null };
type Device = { id: number; hostname: string; created_at: string; last_seen_at: string | null; revoked_at: string | null };

type Dialog =
  | { kind: "team"; team?: Team }
  | { kind: "person"; person?: Person }
  | { kind: "secret"; title: string; label: string; value: string; note: string }
  | { kind: "devices"; person: Person }
  | null;

const ROLES = ["resource", "manager", "admin"] as const;
const hhmm = (t: string) => t.slice(0, 5);
const when = (iso: string | null) => (iso ? new Date(iso).toLocaleString() : "never");

function zones(): string[] {
  try {
    return (Intl as unknown as { supportedValuesOf(k: string): string[] }).supportedValuesOf("timeZone");
  } catch {
    return ["UTC", "Asia/Karachi", "Asia/Dubai", "Europe/London"];
  }
}

function randomPassword() {
  const alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789";
  const bytes = crypto.getRandomValues(new Uint8Array(14));
  return Array.from(bytes, (b) => alphabet[b % alphabet.length]).join("");
}

function Field({ label, children, hint }: { label: string; children: React.ReactElement<{ id?: string }>; hint?: string }) {
  const id = children.props.id;
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-sm font-medium">{label}</label>
      {children}
      {hint && <p className="text-xs text-muted">{hint}</p>}
    </div>
  );
}

function FormError({ error }: { error: string }) {
  return error ? <p role="alert" className="text-sm text-danger">{error}</p> : null;
}

// ---------------------------------------------------------------------------------------------------------------
function TeamForm({ team, people, onDone }: { team?: Team; people: Person[]; onDone: () => void }) {
  const [error, setError] = useState("");
  const managers = people.filter((p) => p.active && (p.role === "manager" || p.role === "admin"));

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const mgr = String(f.get("manager_id") || "");
    const body = {
      name: f.get("name"), timezone: f.get("timezone"), shift_start: f.get("shift_start"), shift_end: f.get("shift_end"),
      break_minutes: Number(f.get("break_minutes")),
      ...(mgr ? { manager_id: Number(mgr) } : team ? { clear_manager: true } : {}),
    };
    try {
      await api(team ? `/admin/teams/${team.id}` : "/admin/teams", { method: team ? "PATCH" : "POST", body: JSON.stringify(body) });
      onDone();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      <Field label="Team name"><input id="team-name" name="name" required defaultValue={team?.name} className="field" /></Field>
      <Field label="Timezone" hint="Days start at midnight in this timezone.">
        <input id="team-tz" name="timezone" required list="tz-list" defaultValue={team?.timezone ?? "Asia/Karachi"} className="field" />
      </Field>
      <div className="grid grid-cols-3 gap-3">
        <Field label="Shift starts"><input id="team-start" name="shift_start" type="time" required defaultValue={hhmm(team?.shift_start ?? "09:00")} className="field" /></Field>
        <Field label="Shift ends"><input id="team-end" name="shift_end" type="time" required defaultValue={hhmm(team?.shift_end ?? "18:00")} className="field" /></Field>
        <Field label="Break (min)"><input id="team-break" name="break_minutes" type="number" min={0} max={240} required defaultValue={team?.break_minutes ?? 60} className="field" /></Field>
      </div>
      <Field label="Manager" hint="Only people with the manager or admin role can manage a team.">
        <select id="team-manager" name="manager_id" defaultValue={team?.manager_id ?? ""} className="field">
          <option value="">No manager</option>
          {managers.map((p) => <option key={p.id} value={p.id}>{p.name} ({p.email})</option>)}
        </select>
      </Field>
      <FormError error={error} />
      <button type="submit" className="btn-primary">{team ? "Save team" : "Add team"}</button>
    </form>
  );
}

function PersonForm({ person, teams, onDone, onCreated }: {
  person?: Person; teams: Team[]; onDone: () => void; onCreated: (email: string, password: string) => void;
}) {
  const me = useUser();
  const [error, setError] = useState("");
  const [password] = useState(randomPassword);
  const self = person?.id === me.id;

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    const team = String(f.get("team_id") || "");
    try {
      if (person) {
        await api(`/admin/people/${person.id}`, {
          method: "PATCH",
          body: JSON.stringify({
            name: f.get("name"), role: f.get("role"), timezone: String(f.get("timezone") || "") || null,
            mantis_username: String(f.get("mantis_username") || ""), google_email: String(f.get("google_email") || ""),
            active: f.get("active") === "on", ...(team ? { team_id: Number(team) } : { clear_team: true }),
          }),
        });
        onDone();
      } else {
        const email = String(f.get("email"));
        await api("/admin/users", {
          method: "POST",
          body: JSON.stringify({ email, name: f.get("name"), role: f.get("role"), password: f.get("password"),
            team_id: team ? Number(team) : null }),
        });
        onCreated(email, String(f.get("password")));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save");
    }
  }

  return (
    <form onSubmit={submit} className="space-y-4">
      {!person && (
        <Field label="Email">
          <input id="person-email" name="email" type="email" required autoComplete="off" spellCheck={false} className="field" />
        </Field>
      )}
      <Field label="Full name"><input id="person-name" name="name" required defaultValue={person?.name} autoComplete="off" className="field" /></Field>
      <div className="grid grid-cols-2 gap-3">
        <Field label="Role">
          <select id="person-role" name="role" defaultValue={person?.role ?? "resource"} disabled={self} className="field">
            {ROLES.map((r) => <option key={r} value={r}>{r[0].toUpperCase() + r.slice(1)}</option>)}
          </select>
        </Field>
        <Field label="Team">
          <select id="person-team" name="team_id" defaultValue={person?.team_id ?? ""} className="field">
            <option value="">No team</option>
            {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </Field>
      </div>
      {self && <input type="hidden" name="role" value={person!.role} />}
      {person ? (
        <>
          <Field label="Timezone override" hint="Leave empty to use the team's timezone.">
            <input id="person-tz" name="timezone" list="tz-list" defaultValue={person.timezone ?? ""} className="field" />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Mantis username" hint="Empty: matched by email, then by the part before @.">
              <input id="person-mantis" name="mantis_username" defaultValue={person.mantis_username ?? ""} autoComplete="off" className="field" />
            </Field>
            <Field label="Google account" hint="Empty: their email above.">
              <input id="person-google" name="google_email" type="email" defaultValue={person.google_email ?? ""} autoComplete="off" className="field" />
            </Field>
          </div>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" name="active" defaultChecked={person.active} disabled={self} className="h-4 w-4" />
            Active (unticking signs them out and stops their PCs from uploading)
          </label>
          {self && <input type="hidden" name="active" value="on" />}
        </>
      ) : (
        <Field label="First password" hint="Generated for you. You'll see it again after saving, to pass on. They can change it on the Account page.">
          <input id="person-password" name="password" required minLength={10} defaultValue={password} className="field font-mono" />
        </Field>
      )}
      <FormError error={error} />
      <button type="submit" className="btn-primary">{person ? "Save changes" : "Add person"}</button>
    </form>
  );
}

function Devices({ person }: { person: Person }) {
  const [rows, setRows] = useState<Device[] | null>(null);
  const [error, setError] = useState("");
  const load = useCallback(() => {
    api<Device[]>(`/admin/people/${person.id}/devices`).then(setRows).catch((e) => setError(e.message));
  }, [person.id]);
  useEffect(load, [load]);

  async function revoke(d: Device) {
    if (!confirm(`Disconnect ${d.hostname}? Its agent stops uploading and needs a new setup code.`)) return;
    try {
      await api(`/admin/devices/${d.id}/revoke`, { method: "POST" });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not revoke");
    }
  }

  if (!rows) return <p className="text-sm text-muted" role="status">Loading…</p>;
  return (
    <div className="space-y-3">
      {rows.length === 0 && <p className="text-sm text-muted">No PCs linked yet. Give {person.name} a setup code.</p>}
      <ul className="divide-y divide-line">
        {rows.map((d) => (
          <li key={d.id} className="flex items-center justify-between gap-3 py-2 text-sm">
            <div>
              <p className="font-medium">{d.hostname}</p>
              <p className="text-xs text-muted">Linked {when(d.created_at)} · last upload {when(d.last_seen_at)}</p>
            </div>
            {d.revoked_at
              ? <span className="text-xs text-muted">Disconnected</span>
              : <button onClick={() => revoke(d)} className="btn-secondary px-3 py-1 text-danger">Disconnect</button>}
          </li>
        ))}
      </ul>
      <FormError error={error} />
    </div>
  );
}

// ---------------------------------------------------------------------------------------------------------------
function AdminPage() {
  const me = useUser();
  const [teams, setTeams] = useState<Team[]>([]);
  const [people, setPeople] = useState<Person[] | null>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [error, setError] = useState("");
  const tzList = useMemo(zones, []);

  const load = useCallback(async () => {
    try {
      const [t, p] = await Promise.all([api<Team[]>("/admin/teams"), api<Person[]>("/admin/people")]);
      setTeams(t);
      setPeople(p);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load");
    }
  }, []);
  useEffect(() => { load(); }, [load]);

  const teamName = (id: number | null) => teams.find((t) => t.id === id)?.name ?? "—";
  const personName = (id: number | null) => people?.find((p) => p.id === id)?.name ?? "—";
  const done = () => { setDialog(null); load(); };

  async function resetPassword(p: Person) {
    if (!confirm(`Reset ${p.name}'s password? They will be signed out everywhere.`)) return;
    try {
      const { password } = await api<{ password: string }>(`/admin/people/${p.id}/reset-password`, { method: "POST" });
      setDialog({ kind: "secret", title: `New password for ${p.name}`, label: "Password", value: password,
        note: "Shown only now. Pass it on privately; they can change it on the Account page." });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not reset");
    }
  }

  async function setupCode(p: Person) {
    try {
      const { code, expires_at } = await api<{ code: string; expires_at: string }>(`/admin/users/${p.id}/enrol-codes`, { method: "POST" });
      setDialog({ kind: "secret", title: `Setup code for ${p.name}`, label: "Setup code", value: code,
        note: `Links one PC to ${p.name}. Works once, expires ${new Date(expires_at).toLocaleString()}.` });
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create a code");
    }
  }

  if (me.role !== "admin") return <p role="alert" className="text-danger">Only admins can open this page.</p>;

  return (
    <div className="space-y-8">
      <datalist id="tz-list">{tzList.map((z) => <option key={z} value={z} />)}</datalist>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      <section aria-labelledby="teams-h" className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 id="teams-h" className="text-lg font-semibold">Teams</h2>
          <button onClick={() => setDialog({ kind: "team" })} className="btn-primary">Add team</button>
        </div>
        <div className="card overflow-x-auto p-0 sm:p-0">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-muted">
              <tr><th className="px-4 py-2 font-medium">Team</th><th className="px-4 py-2 font-medium">Shift</th>
                <th className="px-4 py-2 font-medium">Timezone</th><th className="px-4 py-2 font-medium">Manager</th>
                <th className="px-4 py-2 font-medium">People</th><th className="px-4 py-2"><span className="sr-only">Actions</span></th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {teams.length === 0 && <tr><td colSpan={6} className="px-4 py-4 text-muted">No teams yet. A team sets the shift, break and timezone its people are measured against.</td></tr>}
              {teams.map((t) => (
                <tr key={t.id}>
                  <td className="px-4 py-2 font-medium">{t.name}</td>
                  <td className="px-4 py-2 whitespace-nowrap">{hhmm(t.shift_start)}–{hhmm(t.shift_end)} · {t.break_minutes} min break</td>
                  <td className="px-4 py-2">{t.timezone}</td>
                  <td className="px-4 py-2">{personName(t.manager_id)}</td>
                  <td className="px-4 py-2">{people?.filter((p) => p.team_id === t.id && p.active).length ?? 0}</td>
                  <td className="px-4 py-2 text-right"><button onClick={() => setDialog({ kind: "team", team: t })} className="btn-secondary px-3 py-1">Edit</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section aria-labelledby="people-h" className="space-y-3">
        <div className="flex items-center justify-between">
          <h2 id="people-h" className="text-lg font-semibold">People</h2>
          <button onClick={() => setDialog({ kind: "person" })} className="btn-primary">Add person</button>
        </div>
        <div className="card overflow-x-auto p-0 sm:p-0">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-line text-muted">
              <tr><th className="px-4 py-2 font-medium">Person</th><th className="px-4 py-2 font-medium">Role</th>
                <th className="px-4 py-2 font-medium">Team</th><th className="px-4 py-2 font-medium">PCs</th>
                <th className="px-4 py-2"><span className="sr-only">Actions</span></th></tr>
            </thead>
            <tbody className="divide-y divide-line">
              {people === null && <tr><td colSpan={5} className="px-4 py-4 text-muted">Loading…</td></tr>}
              {people?.map((p) => (
                <tr key={p.id} className={p.active ? "" : "opacity-60"}>
                  <td className="px-4 py-2">
                    <p className="font-medium">{p.name} {!p.active && <span className="ml-1 rounded bg-bg px-1.5 py-0.5 text-xs">Disabled</span>}</p>
                    <p className="text-xs text-muted">{p.email}</p>
                  </td>
                  <td className="px-4 py-2 capitalize">{p.role}</td>
                  <td className="px-4 py-2">{teamName(p.team_id)}</td>
                  <td className="px-4 py-2">
                    <button onClick={() => setDialog({ kind: "devices", person: p })} className="text-left underline-offset-2 hover:underline">
                      {p.devices} linked
                      <span className="block text-xs text-muted">last upload {when(p.last_seen_at)}</span>
                    </button>
                  </td>
                  <td className="px-4 py-2">
                    <div className="flex flex-wrap justify-end gap-2">
                      <button onClick={() => setDialog({ kind: "person", person: p })} className="btn-secondary px-3 py-1">Edit</button>
                      <button onClick={() => setupCode(p)} disabled={!p.active} className="btn-secondary px-3 py-1">Setup code</button>
                      <button onClick={() => resetPassword(p)} className="btn-secondary px-3 py-1">Reset password</button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <Modal open={dialog?.kind === "team"} title={dialog?.kind === "team" && dialog.team ? `Edit ${dialog.team.name}` : "Add team"} onClose={() => setDialog(null)}>
        {dialog?.kind === "team" && <TeamForm team={dialog.team} people={people ?? []} onDone={done} />}
      </Modal>
      <Modal open={dialog?.kind === "person"} title={dialog?.kind === "person" && dialog.person ? `Edit ${dialog.person.name}` : "Add person"} onClose={() => setDialog(null)}>
        {dialog?.kind === "person" && (
          <PersonForm person={dialog.person} teams={teams} onDone={done}
            onCreated={(email, password) => {
              load();
              setDialog({ kind: "secret", title: "Person added", label: `First password for ${email}`, value: password,
                note: "Pass it on privately. They sign in at this site, then use Downloads to set up their PC." });
            }} />
        )}
      </Modal>
      <Modal open={dialog?.kind === "secret"} title={dialog?.kind === "secret" ? dialog.title : ""} onClose={() => setDialog(null)}>
        {dialog?.kind === "secret" && (
          <div className="space-y-2">
            <CopyField label={dialog.label} value={dialog.value} />
            <p className="text-sm text-muted">{dialog.note}</p>
          </div>
        )}
      </Modal>
      <Modal open={dialog?.kind === "devices"} title={dialog?.kind === "devices" ? `${dialog.person.name}'s PCs` : ""} onClose={() => { setDialog(null); load(); }}>
        {dialog?.kind === "devices" && <Devices person={dialog.person} />}
      </Modal>
    </div>
  );
}

const TABS = [
  { key: "people", label: "People & teams" },
  { key: "clients", label: "Clients" },
  { key: "rules", label: "Category rules" },
  { key: "integrations", label: "Integrations" },
  { key: "template", label: "Excel template" },
] as const;

function AdminTabs() {
  const me = useUser();
  const router = useRouter();
  const tab = useSearchParams().get("tab") ?? "people";
  if (me.role !== "admin") return <p role="alert" className="text-danger">Only admins can open this page.</p>;
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-semibold">Admin</h1>
      <nav aria-label="Admin sections" className="flex flex-wrap gap-1 border-b border-line">
        {TABS.map((t) => (
          <button key={t.key} onClick={() => router.push(`?tab=${t.key}`)} aria-current={tab === t.key ? "page" : undefined}
            className="-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted hover:text-fg aria-[current=page]:border-accent aria-[current=page]:text-fg">
            {t.label}
          </button>
        ))}
      </nav>
      {tab === "people" && <AdminPage />}
      {tab === "clients" && <Clients />}
      {tab === "rules" && <Rules />}
      {tab === "integrations" && <Integrations />}
      {tab === "template" && <Template />}
    </div>
  );
}

export default function Page() {
  return (
    <Shell>
      <Suspense>
        <AdminTabs />
      </Suspense>
    </Shell>
  );
}
