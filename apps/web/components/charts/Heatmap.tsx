"use client";

import { hm, seqStep } from "@/lib/viz";

import { TableView, useTooltip } from "./Tooltip";

/** Rows (days) × hours, one blue ramp for minutes of the chosen bucket in each hour. */
export default function Heatmap({ rows, hours, title }: {
  rows: { key: string; label: string; cells: Record<number, number> }[]; hours: number[]; title: string;
}) {
  const { show, hide, node } = useTooltip();
  const max = 3600;
  return (
    <figure>
      <div className="overflow-x-auto">
        <table className="border-separate border-spacing-[2px] text-[10px]" aria-label={title}>
          <thead>
            <tr><th />{hours.map((h) => <th key={h} className="px-0.5 font-normal text-muted">{String(h).padStart(2, "0")}</th>)}</tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.key}>
                <th className="pr-2 text-right font-normal text-muted whitespace-nowrap">{r.label}</th>
                {hours.map((h) => {
                  const v = r.cells[h] ?? 0;
                  return (
                    <td key={h} tabIndex={0} className="h-6 w-7 min-w-7 rounded-sm" style={{ background: seqStep(v, max) }}
                      onPointerMove={(e) => show(e, <><b>{r.label} {String(h).padStart(2, "0")}:00</b><br />{hm(v)} {title.toLowerCase()}</>)}
                      onFocus={(e) => show(e, `${r.label} ${h}:00 ${hm(v)}`)} onPointerLeave={hide} onBlur={hide} />
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex items-center gap-1 text-[10px] text-muted">
        0m {[0, 1, 2, 3, 4, 5].map((i) => <span key={i} className="inline-block h-3 w-5 rounded-sm" style={{ background: `var(--seq-${i})` }} />)} 60m per hour
      </div>
      <TableView head={["Day", ...hours.map((h) => `${h}:00`)]} rows={rows.map((r) => [r.label, ...hours.map((h) => hm(r.cells[h] ?? 0))])} />
      {node}
    </figure>
  );
}
