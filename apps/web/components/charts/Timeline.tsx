"use client";

import { BUCKET_LABEL, bucketColor, bucketOf, clock, hm } from "@/lib/viz";

import { TableView, useTooltip } from "./Tooltip";

type Session = { id: number; start: string; end: string; seconds: number; klass: string; category: string | null;
  app: string | null; domain: string | null; title: string | null };
type Meeting = { id: number; title: string; start: string; end: string; duration_s: number; status: string };

const W = 1000;
const PAD = 22; // room for the first and last hour labels
const LANE = 26;
const COUNTED = new Set(["confirmed", "attended", "multitasking"]);

/** The day as lanes: what was in front (coloured by bucket) and calendar meetings, over the shift. */
export default function Timeline({ day, tz, sessions, meetings, shiftStart, shiftEnd }: {
  day: string; tz: string; sessions: Session[]; meetings: Meeting[]; shiftStart: string; shiftEnd: string;
}) {
  const { show, hide, node } = useTooltip();
  // Minutes since local midnight, read through the timezone so the axis matches the person's day.
  const minuteOf = (iso: string) => {
    const [h, m] = clock(iso, tz).split(":").map(Number);
    const d = new Date(iso).toLocaleDateString("en-CA", { timeZone: tz });
    return d < day ? 0 : d > day ? 1440 : h * 60 + m + new Date(iso).getSeconds() / 60;
  };
  const toMin = (hhmm: string) => Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(3, 5));
  const s0 = toMin(shiftStart), s1 = toMin(shiftEnd);
  const starts = sessions.map((s) => minuteOf(s.start));
  const ends = sessions.map((s) => minuteOf(s.end));
  const lo = Math.floor(Math.min(s0, ...starts, ...meetings.map((m) => minuteOf(m.start))) / 60) * 60;
  const hi = Math.ceil(Math.max(s1, ...ends, ...meetings.map((m) => minuteOf(m.end))) / 60) * 60;
  const x = (m: number) => PAD + ((m - lo) / (hi - lo)) * (W - 2 * PAD);
  const hours = Array.from({ length: (hi - lo) / 60 + 1 }, (_, i) => lo + i * 60);
  const label = (s: Session) => s.domain || s.app || BUCKET_LABEL[bucketOf(s.klass)];

  return (
    <figure>
      <svg viewBox={`0 0 ${W} ${LANE * 2 + 34}`} className="w-full" role="img"
        aria-label={`Timeline from ${hours[0] / 60}:00 to ${hours.at(-1)! / 60}:00 with ${sessions.length} activity blocks and ${meetings.length} meetings`}>
        <rect x={x(s0)} y={0} width={x(s1) - x(s0)} height={LANE * 2 + 12} fill="rgb(var(--bg))" />
        {hours.map((h) => (
          <g key={h}>
            <line x1={x(h)} x2={x(h)} y1={0} y2={LANE * 2 + 12} stroke="var(--grid)" strokeWidth={1} />
            <text x={x(h)} y={LANE * 2 + 28} textAnchor="middle" fontSize={11} fill="rgb(var(--muted))">
              {String(h / 60).padStart(2, "0")}:00
            </text>
          </g>
        ))}
        <text x={PAD} y={14} fontSize={10} fill="rgb(var(--muted))">Activity</text>
        {sessions.map((s, i) => {
          const a = x(starts[i]), b = x(ends[i]);
          const b2 = bucketOf(s.klass);
          return (
            <rect key={s.id} x={a} y={18} width={Math.max(1.5, b - a - 0.5)} height={LANE - 8} rx={2}
              fill={bucketColor(b2)} tabIndex={0}
              onPointerMove={(e) => show(e, <>
                <b>{clock(s.start, tz)}–{clock(s.end, tz)}</b> · {hm(s.seconds)}<br />
                {BUCKET_LABEL[b2]}{s.category ? ` · ${s.category}` : ""}<br />
                <span className="text-muted">{label(s)}{s.title ? `: ${s.title}` : ""}</span></>)}
              onFocus={(e) => show(e, `${clock(s.start, tz)} ${label(s)} ${hm(s.seconds)}`)}
              onPointerLeave={hide} onBlur={hide} />
          );
        })}
        <text x={PAD} y={LANE + 22} fontSize={10} fill="rgb(var(--muted))">Meetings</text>
        {meetings.map((m) => {
          const a = x(minuteOf(m.start)), b = x(minuteOf(m.end));
          const counted = COUNTED.has(m.status);
          return (
            <rect key={m.id} x={a} y={LANE + 26} width={Math.max(2, b - a - 0.5)} height={LANE - 10} rx={2}
              fill={counted ? bucketColor("meeting") : "transparent"} stroke={bucketColor("meeting")} strokeWidth={1.5}
              strokeDasharray={counted ? undefined : "4 3"} tabIndex={0}
              onPointerMove={(e) => show(e, <><b>{m.title}</b><br />{clock(m.start, tz)}–{clock(m.end, tz)} · {hm(m.duration_s)}<br />
                <span className="text-muted">{m.status.replace("_", " ")}</span></>)}
              onFocus={(e) => show(e, `${m.title} ${clock(m.start, tz)}`)} onPointerLeave={hide} onBlur={hide} />
          );
        })}
      </svg>
      <figcaption className="mt-1 text-xs text-muted">Shaded: shift {shiftStart}–{shiftEnd}. Dashed meetings were not counted (unclear or not attended).</figcaption>
      <TableView head={["Start", "End", "Time", "Bucket", "Category", "App or site", "Title"]}
        rows={sessions.map((s) => [clock(s.start, tz), clock(s.end, tz), hm(s.seconds), BUCKET_LABEL[bucketOf(s.klass)],
          s.category ?? "", label(s), s.title ?? ""])} />
      {node}
    </figure>
  );
}
