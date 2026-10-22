"use client";

import { hm } from "@/lib/viz";

import { Swatch, TableView, useTooltip } from "./Tooltip";

export type ClientRow = { client_id: number | null; client: string; total_s: number; web_s: number; email_s: number;
  tickets_s: number; meetings_s: number; manual_s: number; emails_sent: number; emails_received: number;
  tickets: number; ticket_actions: Record<string, number>; issue_types: Record<string, number>; top_sections: string[] };

// Channels reuse the validated categorical slots 1-5, in fixed order.
const CHANNELS = [
  { key: "web_s", label: "Website / backoffice", color: "var(--b-productive)" },
  { key: "email_s", label: "Email", color: "var(--b-meeting)" },
  { key: "tickets_s", label: "Tickets", color: "var(--b-communication)" },
  { key: "meetings_s", label: "Meetings / calls", color: "var(--b-neutral)" },
  { key: "manual_s", label: "Logged off-PC", color: "var(--b-non_work)" },
] as const;

function ticketText(r: ClientRow) {
  const t = r.ticket_actions;
  const parts = [t.reported && `${t.reported} reported`, t.responded && `${t.responded} responses`,
    (t.resolved || t.closed) && `${(t.resolved ?? 0) + (t.closed ?? 0)} resolved`, t.reopened && `${t.reopened} reopened`].filter(Boolean);
  const types = Object.entries(r.issue_types).map(([k, v]) => `${v} ${k}`).join(", ");
  return parts.length ? `${parts.join(" · ")}${types ? ` (${types})` : ""}` : "";
}

/** One row per client: a bar stacked by channel, the total, and what was done for them. */
export default function ClientBars({ rows }: { rows: ClientRow[] }) {
  const { show, hide, node } = useTooltip();
  const max = Math.max(1, ...rows.map((r) => r.total_s));
  const used = CHANNELS.filter((c) => rows.some((r) => r[c.key] > 0));
  return (
    <figure>
      <ul className="mb-3 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {used.map((c) => <li key={c.key} className="flex items-center gap-1.5"><Swatch color={c.color} />{c.label}</li>)}
      </ul>
      <ul className="space-y-3">
        {rows.map((r) => (
          <li key={r.client} className="grid grid-cols-[minmax(7rem,12rem)_1fr_auto] items-center gap-x-3 gap-y-0.5 text-sm">
            <span className={`truncate ${r.client_id ? "font-medium" : "text-muted"}`} title={r.client}>{r.client}</span>
            <div className="flex h-4 gap-[2px]" role="img" aria-label={`${r.client}: ${used.filter((c) => r[c.key]).map((c) => `${c.label} ${hm(r[c.key])}`).join(", ")}`}
              style={{ width: `${Math.max(2, (100 * r.total_s) / max)}%` }}
              onPointerMove={(e) => show(e, <><b>{r.client}</b> · {hm(r.total_s)}
                {used.filter((c) => r[c.key]).map((c) => <div key={c.key} className="flex items-center gap-1.5"><Swatch color={c.color} />{c.label} {hm(r[c.key])}</div>)}
                {r.top_sections.length > 0 && <div className="mt-1 text-muted">{r.top_sections.join(" · ")}</div>}</>)}
              onPointerLeave={hide}>
              {used.filter((c) => r[c.key] > 0).map((c) => (
                <span key={c.key} className="h-full first:rounded-l last:rounded-r" style={{ flexGrow: r[c.key], background: c.color, minWidth: 2 }} />
              ))}
            </div>
            <span className="tabular-nums">{hm(r.total_s)}</span>
            <span className="col-start-2 col-end-4 text-xs text-muted">
              {[r.emails_sent || r.emails_received ? `${r.emails_sent} emails sent, ${r.emails_received} received` : "", ticketText(r),
                r.top_sections[0] ? `Mostly: ${r.top_sections[0]}` : ""].filter(Boolean).join(" · ")}
            </span>
          </li>
        ))}
      </ul>
      <TableView head={["Client", "Total", ...CHANNELS.map((c) => c.label), "Emails sent", "Emails received", "Tickets"]}
        rows={rows.map((r) => [r.client, hm(r.total_s), ...CHANNELS.map((c) => hm(r[c.key])), r.emails_sent, r.emails_received, ticketText(r) || "—"])} />
      {node}
    </figure>
  );
}
