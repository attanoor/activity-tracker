"use client";

import { useEffect, useMemo, useState } from "react";

import Heading from "@/components/Heading";
import PeriodSummary from "@/components/PeriodSummary";
import Shell, { useUser } from "@/components/Shell";
import Heatmap from "@/components/charts/Heatmap";
import StackedColumns from "@/components/charts/StackedColumns";
import { TableView } from "@/components/charts/Tooltip";
import { api } from "@/lib/api";
import { addDays, hm, localDate, type Bucket } from "@/lib/viz";

type Day = { day: string; breakdown: Record<string, number>; active_s: number; overtime_s: number; deep_focus_s: number;
  switches_per_hour: number; meeting_pct: number; hours: ({ hour: number } & Record<string, number>)[];
  work_output: Record<string, Record<string, number>>; dsr: string | null };
const ACTIVE: Bucket[] = ["productive", "meeting", "communication", "neutral", "non_work"];

function mondayOf(day: string) {
  const d = new Date(`${day}T12:00:00Z`);
  return addDays(day, -((d.getUTCDay() + 6) % 7));
}

function Analysis() {
  const me = useUser();
  const [range, setRange] = useState(7);
  const [people, setPeople] = useState<{ id: number; name: string }[]>([]);
  const [who, setWho] = useState<number>(me.id);
  const [days, setDays] = useState<Day[] | null>(null);
  const [error, setError] = useState("");
  const end = localDate();

  useEffect(() => {
    if (me.role === "resource") return;
    api<{ id: number; name: string }[]>("/team/teams").then(async (teams) => {
      const lists = await Promise.all(teams.map((t) => api<{ id: number; name: string }[]>(`/team/${t.id}/members`)));
      const all = new Map<number, string>([[me.id, `${me.name} (me)`]]);
      lists.flat().forEach((p) => all.set(p.id, p.id === me.id ? `${me.name} (me)` : p.name));
      setPeople([...all].map(([id, name]) => ({ id, name })));
    }).catch(() => undefined);
  }, [me]);

  useEffect(() => {
    setDays(null);
    setError("");
    const url = who === me.id ? `/me/trend?end=${end}&days=${range}` : `/people/${who}/trend?end=${end}&days=${range}`;
    api<{ days: Day[] }>(url).then((r) => setDays(r.days)).catch((e) => setError(e.message));
  }, [who, range, end, me.id]);

  const worked = useMemo(() => (days ?? []).filter((d) => d.active_s >= 1800), [days]);
  const avg = (f: (d: Day) => number) => (worked.length ? worked.reduce((s, d) => s + f(d), 0) / worked.length : 0);
  const hours = useMemo(() => {
    const hs = new Set<number>();
    (days ?? []).forEach((d) => d.hours.forEach((h) => hs.add(h.hour)));
    return [...hs].sort((a, b) => a - b);
  }, [days]);
  const label = (day: string) => new Date(`${day}T12:00:00Z`).toLocaleDateString("en-GB", { weekday: "short", day: "numeric" });

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <Heading level={1}>Analysis</Heading>
        <div className="flex flex-wrap gap-2">
          {people.length > 1 && (
            <>
              <label htmlFor="who" className="sr-only">Person</label>
              <select id="who" value={who} onChange={(e) => setWho(Number(e.target.value))} className="field w-auto">
                {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </>
          )}
          <div role="group" aria-label="Range" className="flex gap-1">
            {[7, 30].map((n) => (
              <button key={n} onClick={() => setRange(n)} aria-pressed={range === n}
                className="btn-secondary aria-pressed:bg-accent aria-pressed:text-accent-fg">Last {n} days</button>
            ))}
          </div>
        </div>
      </div>
      {error && <p role="alert" className="text-danger">{error}</p>}
      {!days && !error && <p role="status" className="text-muted">Loading… (days not analysed yet are computed now)</p>}
      {days && (
        <>
          <section aria-label="Averages per working day" className="grid grid-cols-2 gap-3 sm:grid-cols-5">
            {[["Productive", hm(avg((d) => d.breakdown.productive))], ["Meetings", hm(avg((d) => d.breakdown.meeting))],
              ["Email & chat", hm(avg((d) => d.breakdown.communication))], ["Deep focus", hm(avg((d) => d.deep_focus_s))],
              ["Outside shift", hm(avg((d) => d.overtime_s))]].map(([l, v]) => (
              <div key={l} className="card p-4 sm:p-4"><p className="text-xs text-muted">{l} per working day</p>
                <p className="mt-1 text-2xl font-semibold">{v}</p></div>
            ))}
          </section>
          <p className="text-xs text-muted">{worked.length} working days in range (days with at least 30 minutes tracked).</p>

          <section className="card space-y-3" aria-labelledby="h-trend">
            <Heading id="h-trend">Active time per day</Heading>
            <StackedColumns unit="Day" buckets={ACTIVE} max={Math.max(9 * 3600, ...days.map((d) => ACTIVE.reduce((s, b) => s + d.breakdown[b], 0)))}
              columns={days.map((d) => ({ key: d.day, label: label(d.day), values: d.breakdown }))} />
          </section>

          <section className="card space-y-3" aria-labelledby="h-heat">
            <Heading id="h-heat">Productive time by hour</Heading>
            <Heatmap title="Productive" hours={hours}
              rows={days.filter((d) => d.active_s > 0).map((d) => ({ key: d.day, label: label(d.day),
                cells: Object.fromEntries(d.hours.map((h) => [h.hour, h.productive])) }))} />
          </section>

          <section className="card space-y-3" aria-labelledby="h-rows">
            <Heading id="h-rows">Day by day</Heading>
            <TableView head={["Day", "Productive", "Meetings", "Meeting % of shift", "Email & chat", "Non-work", "Idle", "Deep focus",
              "Switches/hour", "Outside shift", "Tickets", "Emails", "Report"]}
              rows={days.map((d) => [label(d.day), hm(d.breakdown.productive), hm(d.breakdown.meeting), `${d.meeting_pct.toFixed(0)}%`,
                hm(d.breakdown.communication), hm(d.breakdown.non_work), hm(d.breakdown.idle), hm(d.deep_focus_s), d.switches_per_hour,
                hm(d.overtime_s), d.work_output.mantis?.tickets ?? 0,
                (d.work_output.gmail?.replied ?? 0) + (d.work_output.gmail?.new_thread ?? 0), d.dsr ?? "—"])} />
          </section>

          <section className="card grid gap-6 md:grid-cols-2" aria-label="AI summaries">
            <PeriodSummary base={`/people/${who}`} period="week" start={mondayOf(addDays(end, -7))} />
            <PeriodSummary base={`/people/${who}`} period="month" start={`${end.slice(0, 7)}-01`} />
          </section>
        </>
      )}
    </div>
  );
}

export default function Page() {
  return (
    <Shell>
      <Analysis />
    </Shell>
  );
}
