"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";

import Heading from "@/components/Heading";
import PeriodSummary from "@/components/PeriodSummary";
import Shell, { useUser } from "@/components/Shell";
import { Swatch, useTooltip } from "@/components/charts/Tooltip";
import { api } from "@/lib/api";
import { addDays, BUCKET_LABEL, BUCKETS, bucketColor, hm, localDate } from "@/lib/viz";

type Row = { id: number; name: string; email: string; breakdown: Record<string, number>; worked_s: number; overtime_s: number;
  deep_focus_s: number; meeting_pct: number; tickets: number; emails: number; dsr: string | null; ai_status: string | null;
  last_upload: string | null };
type TeamDay = { team: { id: number; name: string; shift_start: string; shift_end: string; break_minutes: number }; day: string; rows: Row[];
  summary: { content: { summary: string; risks: string[]; suggestions: string[]; ai_status: string }; generated_at: string } | null };

const REPORT_LABEL: Record<string, string> = { draft: "Draft (not submitted)", submitted: "Submitted", sent: "Sent to you" };

function MiniBar({ bd }: { bd: Record<string, number> }) {
  const { show, hide, node } = useTooltip();
  const total = BUCKETS.reduce((s, b) => s + (bd[b] ?? 0), 0) || 1;
  return (
    <div className="flex h-3 w-40 gap-[2px] overflow-hidden rounded" role="img"
      aria-label={BUCKETS.filter((b) => bd[b]).map((b) => `${BUCKET_LABEL[b]} ${hm(bd[b])}`).join(", ")}
      onPointerMove={(e) => show(e, <>{BUCKETS.filter((b) => bd[b]).map((b) => (
        <div key={b} className="flex items-center gap-1.5"><Swatch color={bucketColor(b)} />{BUCKET_LABEL[b]} {hm(bd[b])}</div>))}</>)}
      onPointerLeave={hide}>
      {BUCKETS.filter((b) => bd[b]).map((b) => <div key={b} style={{ width: `${(100 * bd[b]) / total}%`, background: bucketColor(b) }} />)}
      {node}
    </div>
  );
}

function TeamView() {
  const me = useUser();
  const router = useRouter();
  const params = useSearchParams();
  const [teams, setTeams] = useState<{ id: number; name: string }[] | null>(null);
  const [data, setData] = useState<TeamDay | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const day = params.get("d") ?? localDate();
  const teamId = Number(params.get("team")) || teams?.[0]?.id;

  useEffect(() => { api<{ id: number; name: string }[]>("/team/teams").then(setTeams).catch((e) => setError(e.message)); }, []);
  const load = useCallback(() => {
    if (!teamId) return;
    setData(null);
    api<TeamDay>(`/team/${teamId}/day/${day}`).then(setData).catch((e) => setError(e.message));
  }, [teamId, day]);
  useEffect(load, [load]);

  const go = (d: string, t = teamId) => router.push(`?team=${t}&d=${d}`);

  if (me.role === "resource") return <p role="alert" className="text-danger">The team view is for managers and admins.</p>;
  if (teams && teams.length === 0) return <p className="text-muted">You don&apos;t manage a team yet. An admin can set you as a team&apos;s manager in Admin → Teams.</p>;

  async function summarise() {
    setBusy(true);
    try {
      await api(`/team/${teamId}/day/${day}/summary`, { method: "POST" });
      load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not summarise");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <Heading level={1}>Team</Heading>
          {data && <p className="text-sm text-muted">{data.team.name} · shift {data.team.shift_start.slice(0, 5)}–{data.team.shift_end.slice(0, 5)}</p>}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {teams && teams.length > 1 && (
            <>
              <label htmlFor="team-pick" className="sr-only">Team</label>
              <select id="team-pick" value={teamId} onChange={(e) => go(day, Number(e.target.value))} className="field w-auto">
                {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
              </select>
            </>
          )}
          <button onClick={() => go(addDays(day, -1))} className="btn-secondary px-3" aria-label="Previous day">←</button>
          <label htmlFor="team-day" className="sr-only">Day</label>
          <input id="team-day" type="date" value={day} max={localDate()} onChange={(e) => e.target.value && go(e.target.value)} className="field w-auto" />
          <button onClick={() => go(addDays(day, 1))} disabled={day >= localDate()} className="btn-secondary px-3" aria-label="Next day">→</button>
          {teamId && <a href={`/api/team/${teamId}/day/${day}/export/xlsx`} className="btn-secondary">Team Excel</a>}
        </div>
      </div>
      {error && <p role="alert" className="text-danger">{error}</p>}
      {!data && !error && <p role="status" className="text-muted">Loading the team&apos;s day…</p>}
      {data && (
        <>
          <section className="card overflow-x-auto p-0 sm:p-0" aria-label="People">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-line text-muted">
                <tr>
                  {["Person", "Shift", "Worked", "Productive", "Meetings", "Deep focus", "Outside shift", "Tickets", "Emails", "Report"].map((h) =>
                    <th key={h} className="whitespace-nowrap px-4 py-2 font-medium">{h}</th>)}
                </tr>
              </thead>
              <tbody className="divide-y divide-line tabular-nums">
                {data.rows.map((r) => (
                  <tr key={r.id}>
                    <td className="px-4 py-2">
                      <Link href={`/people/${r.id}?d=${day}`} className="font-medium underline-offset-2 hover:underline">{r.name}</Link>
                      <p className="text-xs text-muted">last upload {r.last_upload ? new Date(r.last_upload).toLocaleString() : "never"}</p>
                    </td>
                    <td className="px-4 py-2"><MiniBar bd={r.breakdown} /></td>
                    <td className="px-4 py-2">{hm(r.worked_s)}</td>
                    <td className="px-4 py-2">{hm(r.breakdown.productive)}</td>
                    <td className="px-4 py-2">{hm(r.breakdown.meeting)} <span className="text-xs text-muted">{r.meeting_pct.toFixed(0)}%</span></td>
                    <td className="px-4 py-2">{hm(r.deep_focus_s)}</td>
                    <td className={`px-4 py-2 ${r.overtime_s >= 3600 ? "font-semibold" : ""}`}>{hm(r.overtime_s)}</td>
                    <td className="px-4 py-2">{r.tickets}</td>
                    <td className="px-4 py-2">{r.emails}</td>
                    <td className="px-4 py-2 whitespace-nowrap">{r.dsr ? REPORT_LABEL[r.dsr] : <span className="text-muted">None yet</span>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <ul className="flex flex-wrap gap-x-4 gap-y-1 border-t border-line px-4 py-2 text-xs text-muted">
              {BUCKETS.map((b) => <li key={b} className="flex items-center gap-1.5"><Swatch color={bucketColor(b)} />{BUCKET_LABEL[b]}</li>)}
            </ul>
          </section>

          <div className="grid gap-6 md:grid-cols-2">
            <section className="card space-y-3" aria-labelledby="h-team-sum">
              <div className="flex items-center justify-between gap-2">
                <Heading id="h-team-sum">Team summary</Heading>
                <button onClick={summarise} disabled={busy} className="btn-secondary px-3 py-1 text-sm">
                  {busy ? "Writing…" : data.summary ? "Regenerate" : "Generate"}</button>
              </div>
              {data.summary ? (
                <div className="space-y-2 text-sm">
                  <p>{data.summary.content.summary}</p>
                  {data.summary.content.risks.length > 0 && <><p className="text-xs uppercase tracking-wide text-muted">Risks</p>
                    <ul className="list-disc pl-5">{data.summary.content.risks.map((x) => <li key={x}>{x}</li>)}</ul></>}
                  {data.summary.content.suggestions.length > 0 && <><p className="text-xs uppercase tracking-wide text-muted">Suggestions</p>
                    <ul className="list-disc pl-5">{data.summary.content.suggestions.map((x) => <li key={x}>{x}</li>)}</ul></>}
                  <p className="text-xs text-muted">{new Date(data.summary.generated_at).toLocaleString()}</p>
                </div>
              ) : <p className="text-sm text-muted">Written automatically after the shift, or generate it now.</p>}
            </section>
            <section className="card space-y-6" aria-label="Period summaries">
              <PeriodSummary base={`/team/${data.team.id}`} period="week" start={addDays(day, -7)} />
            </section>
          </div>
        </>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <Shell>
      <Suspense>
        <TeamView />
      </Suspense>
    </Shell>
  );
}
