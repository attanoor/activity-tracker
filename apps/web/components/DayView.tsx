"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import Heading from "@/components/Heading";
import ManualEntries from "@/components/ManualEntries";
import { useUser } from "@/components/Shell";
import ClientBars, { type ClientRow } from "@/components/charts/ClientBars";
import ShiftBar from "@/components/charts/ShiftBar";
import StackedColumns from "@/components/charts/StackedColumns";
import Timeline from "@/components/charts/Timeline";
import { TableView } from "@/components/charts/Tooltip";
import { api } from "@/lib/api";
import { addDays, BUCKET_LABEL, bucketOf, clock, hm, localDate } from "@/lib/viz";

type Task = { id: string; title: string; summary: string; status: string; seconds: number; category: string | null; refs: string[];
  client?: string | null };
type Content = { tasks: Task[]; highlights: string[]; blockers: string[]; tomorrow: string[]; insights: string;
  suggestions?: { text: string; metric: string }[]; sections: Record<string, string>; meetings: Meeting[];
  work_output: Record<string, Record<string, number>> };
type Dsr = { id: number; status: string; ai_status: string; model: string; content: Content; edited: boolean;
  generated_at: string; submitted_at: string | null; sent_at: string | null; editable?: boolean; locked_reason?: string;
  edit_deadline?: string; reopened?: boolean };
type Meeting = { id: number; title: string; start: string; end: string; duration_s: number; status: string; attendees?: number };
type Overview = {
  user: { id: number; name: string }; day: string; tz: string;
  sessions: { id: number; start: string; end: string; seconds: number; kind: string; klass: string; category: string | null;
    app: string | null; domain: string | null; title: string | null }[];
  analysis: {
    shift: { start: string; end: string; break_minutes: number; seconds: number }; breakdown: Record<string, number>;
    overtime: { before_s: number; after_s: number }; active_s: number; worked_in_shift_s: number; expected_work_s: number;
    hours: ({ hour: number; in_shift: boolean } & Record<string, number>)[];
    top_targets: { target: string; seconds: number; klass: string; category: string | null; sessions: number }[];
    long_low_value: { target: string; title: string | null; seconds: number; start: string }[];
    focus: { deep_blocks: number; deep_s: number; longest: { seconds: number; main: string; start: string } | null };
    switching: { switches: number; per_hour: number }; communication_checks: Record<string, number>;
    meetings: Meeting[]; adhoc_calls: { start: string; end: string; duration_s: number }[];
    meeting_load: { count: number; seconds: number; pct_of_shift: number; back_to_back: number; short_gaps: number; short_gap_s: number };
    by_client?: { rows: ClientRow[]; total_s: number; client_s: number };
  };
  compare: Record<string, { value: number; avg_7d: number | null; team_avg: number | null; flag: { vs: string; direction: string } | null }>;
  actions: { source: string; action: string; object_id: string; at: string; title: string }[];
  work_output: Record<string, Record<string, number>>;
  dsr: Dsr | null;
  generating: boolean;
  generation_error: string | null;
};

const STATUS_LABEL: Record<string, string> = { done: "Done", in_progress: "In progress", blocked: "Blocked" };
const MEETING_LABEL: Record<string, string> = { attended: "Attended", confirmed: "Confirmed by you", multitasking: "Attended, other work alongside",
  unclear: "Unclear: busy with other work", not_attended: "Not attended" };

/** Older or placeholder reports may miss fields; the editor always gets every list. */
function withDefaults(c: Partial<Content>): Content {
  return { tasks: [], highlights: [], blockers: [], tomorrow: [], insights: "", suggestions: [], sections: {}, meetings: [],
    work_output: {}, ...c } as Content;
}

function Tile({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="card p-4 sm:p-4">
      <p className="text-xs text-muted">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
      {note && <p className="mt-0.5 text-xs text-muted">{note}</p>}
    </div>
  );
}

function compareNote(c?: Overview["compare"][string]) {
  if (!c) return undefined;
  if (c.flag) return `${c.flag.direction} than ${c.flag.vs === "usual" ? "your usual" : "the team"}`;
  if (c.avg_7d !== null) return `usual ${hm(c.avg_7d)}`;
  return undefined;
}

function Lines({ label, value, onChange, readOnly }: { label: string; value: string[]; onChange: (v: string[]) => void; readOnly: boolean }) {
  const id = `lines-${label.toLowerCase().replace(/\W+/g, "-")}`;
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-sm font-medium">{label}</label>
      {readOnly ? (
        value.length ? <ul className="list-disc space-y-0.5 pl-5 text-sm">{value.map((v, i) => <li key={i}>{v}</li>)}</ul>
          : <p className="text-sm text-muted">None</p>
      ) : (
        <>
          <textarea id={id} rows={3} value={value.join("\n")} onChange={(e) => onChange(e.target.value.split("\n"))}
            className="field text-sm" aria-describedby={`${id}-hint`} />
          <p id={`${id}-hint`} className="text-xs text-muted">One per line.</p>
        </>
      )}
    </div>
  );
}

function WorkOutput({ wo }: { wo: Overview["work_output"] }) {
  const m = wo.mantis ?? {}, g = wo.gmail ?? {}, d = wo.drive ?? {};
  const items = [
    m.tickets ? `Tickets: ${m.reported ?? 0} reported · ${m.responded ?? 0} responses · ${(m.resolved ?? 0) + (m.closed ?? 0)} resolved` +
      (m.reopened ? ` · ${m.reopened} reopened` : "") + ` (${m.tickets} touched)` : "",
    g.threads ? `Email: ${(g.replied ?? 0) + (g.new_thread ?? 0)} sent (${g.replied ?? 0} replies) across ${g.threads} threads` : "",
    d.files ? `Documents: ${d.created ?? 0} created · ${d.edited ?? 0} edited · ${d.commented ?? 0} commented · ${d.shared ?? 0} shared` : "",
  ].filter(Boolean);
  return items.length ? <ul className="space-y-1 text-sm">{items.map((x) => <li key={x}>{x}</li>)}</ul>
    : <p className="text-sm text-muted">No ticket, email or document actions recorded. Connect Mantis and Google in Admin → Integrations.</p>;
}

export default function DayView({ personId }: { personId?: number }) {
  const me = useUser();
  const router = useRouter();
  const params = useSearchParams();
  const own = personId === undefined;
  const [data, setData] = useState<Overview | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  const [draft, setDraft] = useState<Content | null>(null);
  const [preview, setPreview] = useState(false);
  const [voted, setVoted] = useState<Record<string, boolean>>({});
  const day = params.get("d") ?? localDate();
  const base = own ? "/me" : `/people/${personId}`;

  const load = useCallback(async () => {
    setError("");
    try {
      const o = await api<Overview>(`${own ? "/me" : `/people/${personId}`}/overview/${day}`);
      setData(o);
      setDraft(o.dsr ? withDefaults(structuredClone(o.dsr.content)) : null);
      if (o.generation_error) setError(o.generation_error);
      return o;
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not load the day");
      return null;
    }
  }, [day, own, personId]);
  useEffect(() => { setData(null); load(); }, [load]);

  // While the report is being written in the background, check again every few seconds.
  const generating = data?.generating ?? false;
  useEffect(() => {
    if (!generating) return;
    const t = setInterval(load, 3000);
    return () => clearInterval(t);
  }, [generating, load]);

  const go = (d: string) => router.push(`?d=${d}`);

  async function run(label: string, fn: () => Promise<unknown>) {
    setBusy(label);
    setError("");
    try {
      await fn();
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy("");
    }
  }

  const save = () => api(`/me/dsr/${day}`, { method: "PUT", body: JSON.stringify({
    tasks: draft!.tasks.map(({ id, title, summary, status }) => ({ id, title, summary, status })),
    highlights: draft!.highlights, blockers: draft!.blockers, tomorrow: draft!.tomorrow, insights: draft!.insights }) });

  if (error && !data) return <p role="alert" className="text-danger">{error}</p>;
  if (!data) return <p role="status" className="text-muted">Loading the day… (the first load of a day can take a few seconds)</p>;

  const a = data.analysis, bd = a.breakdown, tz = data.tz;
  const dsr = data.dsr;
  const editable = own && dsr?.status === "draft" && dsr.editable !== false && !preview;
  const clientRows = a.by_client?.rows ?? [];
  const changed = dsr && draft && JSON.stringify(draft) !== JSON.stringify(withDefaults(dsr.content));
  const ot = a.overtime.before_s + a.overtime.after_s;
  const hourCols = a.hours.map((h) => ({ key: String(h.hour), label: `${String(h.hour).padStart(2, "0")}`, values: h, muted: !h.in_shift }));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Heading level={1}>{own ? "My day" : data.user.name}</Heading>
          <p className="text-sm text-muted">
            {new Date(`${day}T12:00:00Z`).toLocaleDateString("en-GB", { weekday: "long", day: "numeric", month: "long", year: "numeric" })}
            {" · "}shift {a.shift.start}–{a.shift.end} with a {a.shift.break_minutes}m break · {tz}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <button onClick={() => go(addDays(day, -1))} className="btn-secondary px-3" aria-label="Previous day">←</button>
          <label className="sr-only" htmlFor="day-pick">Day</label>
          <input id="day-pick" type="date" value={day} max={localDate()} onChange={(e) => e.target.value && go(e.target.value)} className="field w-auto" />
          <button onClick={() => go(addDays(day, 1))} disabled={day >= localDate()} className="btn-secondary px-3" aria-label="Next day">→</button>
          {day !== localDate() && <button onClick={() => go(localDate())} className="btn-secondary">Today</button>}
        </div>
      </div>
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}

      <section aria-label="Key numbers" className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-6">
        <Tile label="Worked in shift" value={hm(a.worked_in_shift_s)} note={`of ${hm(a.expected_work_s)} expected`} />
        <Tile label="Productive" value={hm(bd.productive)} note={compareNote(data.compare.productive)} />
        <Tile label="Meetings" value={hm(bd.meeting)} note={`${a.meeting_load.count} meetings · ${a.meeting_load.pct_of_shift.toFixed(0)}% of shift`} />
        <Tile label="Email & chat" value={hm(bd.communication)} note={compareNote(data.compare.communication)} />
        <Tile label="Idle at desk" value={hm(bd.idle)} note={compareNote(data.compare.idle)} />
        <Tile label="Outside shift" value={hm(ot)} note={ot ? `${hm(a.overtime.before_s)} before · ${hm(a.overtime.after_s)} after` : "none"} />
      </section>

      <section className="card space-y-3" aria-labelledby="h-shift">
        <Heading id="h-shift">Where the {hm(a.shift.seconds)} went</Heading>
        <ShiftBar breakdown={bd} shiftSeconds={a.shift.seconds} />
      </section>

      {clientRows.length > 0 && (
        <section className="card space-y-3" aria-labelledby="h-clients">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <Heading id="h-clients">Time by client</Heading>
            <p className="text-xs text-muted">{hm(a.by_client!.client_s)} for clients of {hm(a.by_client!.total_s)} worked</p>
          </div>
          <ClientBars rows={clientRows} />
          {clientRows.some((r) => r.client_id === null) && (
            <p className="text-xs text-muted">&quot;No client&quot; is internal work, or a site or email the tracker doesn&apos;t know yet.
              {me.role === "admin" ? " Confirm new clients in Admin → Clients." : " Your admin confirms new clients."}</p>
          )}
        </section>
      )}

      <section className="card space-y-3" aria-labelledby="h-timeline">
        <Heading id="h-timeline">Timeline</Heading>
        {data.sessions.length ? (
          <Timeline day={day} tz={tz} sessions={data.sessions} meetings={a.meetings} shiftStart={a.shift.start} shiftEnd={a.shift.end} />
        ) : <p className="text-sm text-muted">Nothing tracked on this day yet. {own && "Check the agent's tray icon is green."}</p>}
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card space-y-3" aria-labelledby="h-hourly">
          <Heading id="h-hourly">Hour by hour</Heading>
          <StackedColumns columns={hourCols} max={3600} unit="Hour" />
          <p className="text-xs text-muted">Faded columns are outside the shift.</p>
        </section>
        <section className="card space-y-3" aria-labelledby="h-focus">
          <Heading id="h-focus">Focus and switching</Heading>
          <dl className="grid grid-cols-2 gap-3 text-sm">
            <div><dt className="text-muted">Longest focus block</dt>
              <dd className="text-lg font-semibold">{a.focus.longest ? hm(a.focus.longest.seconds) : "—"}</dd>
              {a.focus.longest && <dd className="text-xs text-muted">{a.focus.longest.main} from {clock(a.focus.longest.start, tz)}</dd>}</div>
            <div><dt className="text-muted">Focus blocks ≥ 25m</dt><dd className="text-lg font-semibold">{a.focus.deep_blocks}</dd>
              <dd className="text-xs text-muted">{hm(a.focus.deep_s)} in total</dd></div>
            <div><dt className="text-muted">App or site switches</dt><dd className="text-lg font-semibold">{a.switching.per_hour}/hour</dd>
              <dd className="text-xs text-muted">{a.switching.switches} switches</dd></div>
            <div><dt className="text-muted">Email & chat opened</dt>
              <dd className="text-lg font-semibold">{Object.values(a.communication_checks).reduce((s, n) => s + n, 0)} times</dd>
              <dd className="text-xs text-muted">{Object.entries(a.communication_checks).map(([k, v]) => `${k} ${v}`).join(" · ") || "—"}</dd></div>
          </dl>
        </section>
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <section className="card space-y-3" aria-labelledby="h-sinks">
          <Heading id="h-sinks">Where time went by app and site</Heading>
          <ul className="space-y-1.5 text-sm">
            {a.top_targets.map((t) => (
              <li key={t.target} className="grid grid-cols-[1fr_auto] items-center gap-x-3">
                <span className="truncate">{t.target} <span className="text-xs text-muted">{t.category ?? BUCKET_LABEL[bucketOf(t.klass)]}</span></span>
                <span className="tabular-nums">{hm(t.seconds)}</span>
                <span aria-hidden className="col-span-2 h-1.5 rounded-full" style={{
                  width: `${(100 * t.seconds) / Math.max(1, a.top_targets[0].seconds)}%`, background: `var(--b-${bucketOf(t.klass)})` }} />
              </li>
            ))}
          </ul>
          {a.long_low_value.length > 0 && (
            <div>
              <p className="text-sm font-medium">Longest non-work or neutral stretches</p>
              <ul className="mt-1 space-y-0.5 text-sm text-muted">
                {a.long_low_value.map((x) => <li key={x.start}>{clock(x.start, tz)} · {x.target} · {hm(x.seconds)}</li>)}
              </ul>
            </div>
          )}
        </section>
        <section className="card space-y-3" aria-labelledby="h-meetings">
          <Heading id="h-meetings">Meetings and calls</Heading>
          {a.meetings.length === 0 && a.adhoc_calls.length === 0 && <p className="text-sm text-muted">No meetings on the calendar.</p>}
          <ul className="divide-y divide-line">
            {a.meetings.map((m) => (
              <li key={m.id} className="py-2 text-sm">
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="font-medium">{m.title}</span>
                  <span className="tabular-nums text-muted">{clock(m.start, tz)}–{clock(m.end, tz)} · {hm(m.duration_s)}</span>
                </div>
                <p className={`text-xs ${m.status === "unclear" ? "text-danger" : "text-muted"}`}>{MEETING_LABEL[m.status] ?? m.status}</p>
                {own && (m.status === "unclear" || m.status === "confirmed" || m.status === "not_attended") && (
                  <div className="mt-1 flex gap-2">
                    <span className="text-xs">Did you attend?</span>
                    <button className="btn-secondary px-2 py-0.5 text-xs" disabled={!!busy}
                      onClick={() => run("meeting", () => api(`/me/meetings/${m.id}/attendance`, { method: "POST", body: JSON.stringify({ attended: true }) }))}>Yes</button>
                    <button className="btn-secondary px-2 py-0.5 text-xs" disabled={!!busy}
                      onClick={() => run("meeting", () => api(`/me/meetings/${m.id}/attendance`, { method: "POST", body: JSON.stringify({ attended: false }) }))}>No</button>
                  </div>
                )}
              </li>
            ))}
            {a.adhoc_calls.map((c) => (
              <li key={c.start} className="py-2 text-sm">
                <span className="font-medium">Call not on the calendar</span>
                <span className="ml-2 tabular-nums text-muted">{clock(c.start, tz)}–{clock(c.end, tz)} · {hm(c.duration_s)}</span>
              </li>
            ))}
          </ul>
          <p className="text-xs text-muted">{a.meeting_load.back_to_back} back to back · {a.meeting_load.short_gaps} short gaps between meetings ({hm(a.meeting_load.short_gap_s)})</p>
        </section>
      </div>

      {own && (
        <section className="card space-y-3" aria-labelledby="h-manual">
          <Heading id="h-manual">Work away from the PC</Heading>
          <ManualEntries day={day} tz={tz} onChange={load} />
        </section>
      )}

      <section className="card space-y-3" aria-labelledby="h-output">
        <Heading id="h-output">Work output</Heading>
        <WorkOutput wo={data.work_output} />
        {data.actions.length > 0 && (
          <TableView head={["Time", "Source", "Action", "Item"]}
            rows={data.actions.map((x) => [clock(x.at, tz), x.source, x.action.replace("_", " "),
              x.source === "mantis" ? `#${x.object_id} ${x.title}` : x.title])} />
        )}
      </section>

      <section className="card space-y-4" aria-labelledby="h-dsr">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <Heading id="h-dsr">Daily status report</Heading>
            {dsr && (
              <p className="text-xs text-muted">
                <span className="mr-2 rounded bg-bg px-1.5 py-0.5 capitalize text-fg">{dsr.status}</span>
                Written by {dsr.ai_status === "fallback" ? "the tracker (AI unavailable)" : `AI (${dsr.model})`}
                {dsr.ai_status === "partial" && ", some parts completed by the tracker"}
                {dsr.edited && " · edited by you"}
                {dsr.submitted_at && ` · submitted ${new Date(dsr.submitted_at).toLocaleString()}`}
              </p>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {own && (!dsr || (dsr.status === "draft" && dsr.editable !== false)) && (
              <button className="btn-secondary" disabled={!!busy || generating}
                onClick={() => (!changed || confirm("Regenerating replaces your edits. Continue?")) &&
                  run("generate", () => api(`/me/dsr/${day}/generate`, { method: "POST" }))}>
                {generating ? "Writing… (about a minute)" : dsr ? "Regenerate" : "Generate report"}
              </button>
            )}
            {dsr && <a className="btn-secondary" href={`/api${base}/dsr/${day}/export/xlsx`}>Excel</a>}
            {dsr && <a className="btn-secondary" href={`/api${base}/dsr/${day}/export/pdf`}>PDF</a>}
            {dsr && <a className="btn-secondary" href={`/api${base}/dsr/${day}/export/template`}>Company template</a>}
          </div>
        </div>

        {!dsr && <p className="text-sm text-muted">{own ? "The report is drafted automatically after your shift. You can also generate it now." : "No report for this day yet."}</p>}
        {own && dsr && dsr.editable === false && (
          <p role="status" className="rounded-lg bg-bg p-3 text-sm">{dsr.locked_reason}</p>
        )}
        {own && dsr?.reopened && <p className="text-xs text-muted">Reopened by your manager: you can make changes and submit again.</p>}
        {!own && (me.role === "manager" || me.role === "admin") && (dsr?.status !== "draft" || dsr.editable === false) && (
          <button className="btn-secondary" disabled={!!busy}
            onClick={() => confirm(`Reopen this day so ${data.user.name} can change it?`) &&
              run("reopen", () => api(`/people/${personId}/dsr/${day}/reopen`, { method: "POST" }))}>
            {busy === "reopen" ? "Reopening…" : "Reopen this day"}</button>
        )}

        {dsr && draft && (
          <>
            {own && dsr.status === "draft" && (
              <label className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={preview} onChange={(e) => setPreview(e.target.checked)} className="h-4 w-4" />
                Show what my manager will see
              </label>
            )}
            <ol className="space-y-3">
              {draft.tasks.map((t, i) => (
                <li key={t.id} className="rounded-lg border border-line p-3">
                  {editable ? (
                    <div className="space-y-2">
                      <div className="flex flex-wrap gap-2">
                        <label className="sr-only" htmlFor={`t-${t.id}`}>Task title</label>
                        <input id={`t-${t.id}`} value={t.title} maxLength={160} className="field min-w-0 flex-1 font-medium"
                          onChange={(e) => setDraft({ ...draft, tasks: draft.tasks.map((x, j) => j === i ? { ...x, title: e.target.value } : x) })} />
                        <label className="sr-only" htmlFor={`s-${t.id}`}>Status</label>
                        <select id={`s-${t.id}`} value={t.status} className="field w-auto"
                          onChange={(e) => setDraft({ ...draft, tasks: draft.tasks.map((x, j) => j === i ? { ...x, status: e.target.value } : x) })}>
                          {Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                        </select>
                        {t.client && <span className="self-center rounded bg-bg px-1.5 py-0.5 text-xs text-muted">{t.client}</span>}
                        <span className="self-center text-sm tabular-nums text-muted" title="Time comes from tracked activity and can't be edited">{hm(t.seconds)}</span>
                        <button className="btn-secondary px-2" aria-label={`Remove task ${t.title}`}
                          onClick={() => setDraft({ ...draft, tasks: draft.tasks.filter((_, j) => j !== i) })}>Remove</button>
                      </div>
                      <label className="sr-only" htmlFor={`d-${t.id}`}>Summary</label>
                      <textarea id={`d-${t.id}`} rows={2} value={t.summary} maxLength={600} className="field text-sm"
                        onChange={(e) => setDraft({ ...draft, tasks: draft.tasks.map((x, j) => j === i ? { ...x, summary: e.target.value } : x) })} />
                    </div>
                  ) : (
                    <div>
                      <div className="flex flex-wrap items-baseline justify-between gap-2">
                        <p className="font-medium">{t.title}
                          {t.client && <span className="ml-2 rounded bg-bg px-1.5 py-0.5 text-xs font-normal text-muted">{t.client}</span>}</p>
                        <p className="text-sm text-muted">{hm(t.seconds)} · {STATUS_LABEL[t.status]}</p>
                      </div>
                      <p className="mt-1 text-sm">{t.summary}</p>
                    </div>
                  )}
                </li>
              ))}
            </ol>
            <div className="grid gap-4 md:grid-cols-3">
              <Lines label="Highlights" value={draft.highlights} readOnly={!editable} onChange={(v) => setDraft({ ...draft, highlights: v })} />
              <Lines label="Blockers" value={draft.blockers} readOnly={!editable} onChange={(v) => setDraft({ ...draft, blockers: v })} />
              <Lines label="Plan for tomorrow" value={draft.tomorrow} readOnly={!editable} onChange={(v) => setDraft({ ...draft, tomorrow: v })} />
            </div>
            <div className="space-y-1">
              <label htmlFor="insights" className="text-sm font-medium">Insights</label>
              {editable ? <textarea id="insights" rows={3} value={draft.insights} onChange={(e) => setDraft({ ...draft, insights: e.target.value })} className="field text-sm" />
                : <p className="text-sm">{draft.insights || "—"}</p>}
            </div>
            {Object.values(draft.sections ?? {}).some(Boolean) && (
              <details className="text-sm">
                <summary className="cursor-pointer font-medium">Section summaries</summary>
                <dl className="mt-2 space-y-2">
                  {Object.entries(draft.sections).filter(([, v]) => v).map(([k, v]) => (
                    <div key={k}><dt className="text-xs uppercase tracking-wide text-muted">{k}</dt><dd>{v}</dd></div>))}
                </dl>
              </details>
            )}
            {own && !preview && draft.suggestions && draft.suggestions.length > 0 && (
              <div className="rounded-lg bg-bg p-4">
                <p className="text-sm font-medium">Suggestions for you <span className="font-normal text-muted">(only you see these)</span></p>
                <ul className="mt-2 space-y-2 text-sm">
                  {draft.suggestions.map((s) => (
                    <li key={s.text} className="flex flex-wrap items-start justify-between gap-2">
                      <span className="flex-1">{s.text}</span>
                      <span className="flex gap-1">
                        {[true, false].map((useful) => (
                          <button key={String(useful)} aria-pressed={voted[s.text] === useful}
                            className="btn-secondary px-2 py-0.5 text-xs aria-pressed:bg-accent aria-pressed:text-accent-fg"
                            onClick={async () => {
                              await api("/me/suggestions/feedback", { method: "POST", body: JSON.stringify({ day, text: s.text, useful }) });
                              setVoted({ ...voted, [s.text]: useful });
                            }}>{useful ? "Useful" : "Not useful"}</button>
                        ))}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
            {editable && (
              <div className="flex flex-wrap gap-2 border-t border-line pt-4">
                <button className="btn-secondary" disabled={!changed || !!busy} onClick={() => run("save", save)}>
                  {busy === "save" ? "Saving…" : "Save draft"}</button>
                <button className="btn-primary" disabled={!!busy}
                  onClick={() => confirm("Submit this report to your manager? You can't change it afterwards.") &&
                    run("submit", async () => { if (changed) await save(); await api(`/me/dsr/${day}/submit`, { method: "POST" }); })}>
                  {busy === "submit" ? "Submitting…" : "Submit report"}</button>
              </div>
            )}
          </>
        )}
      </section>
    </div>
  );
}
