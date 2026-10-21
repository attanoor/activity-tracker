"use client";

import { BUCKET_LABEL, BUCKETS, bucketColor, hm, type Bucket } from "@/lib/viz";

import { Swatch, TableView, useTooltip } from "./Tooltip";

export type Column = { key: string; label: string; values: Record<string, number>; muted?: boolean };

/** Stacked columns (hours of a day, or days of a range) with 2px gaps, a legend and a per-column tooltip. */
export default function StackedColumns({ columns, buckets = BUCKETS as unknown as Bucket[], max, height = 160, unit }: {
  columns: Column[]; buckets?: Bucket[]; max: number; height?: number; unit: string;
}) {
  const { show, hide, node } = useTooltip();
  const shown = buckets.filter((b) => columns.some((c) => (c.values[b] ?? 0) > 0));
  return (
    <figure>
      <ul className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted">
        {shown.map((b) => <li key={b} className="flex items-center gap-1.5"><Swatch color={bucketColor(b)} />{BUCKET_LABEL[b]}</li>)}
      </ul>
      <div className="flex items-end gap-1 border-b border-[color:var(--axis)]" style={{ height }} role="img"
        aria-label={`${columns.length} columns of time by bucket, up to ${hm(max)} each (${unit})`}>
        {columns.map((c) => {
          const total = shown.reduce((s, b) => s + (c.values[b] ?? 0), 0);
          return (
            <div key={c.key} tabIndex={0} className="flex h-full min-w-0 flex-1 flex-col-reverse gap-[2px] focus:outline focus:outline-2 focus:outline-fg"
              onPointerMove={(e) => show(e, <><b>{c.label}</b> · {hm(total)}
                {shown.filter((b) => c.values[b]).map((b) => (
                  <div key={b} className="flex items-center gap-1.5"><Swatch color={bucketColor(b)} />{BUCKET_LABEL[b]} {hm(c.values[b])}</div>))}</>)}
              onFocus={(e) => show(e, `${c.label}: ${hm(total)}`)} onPointerLeave={hide} onBlur={hide}>
              {shown.map((b) => {
                const v = c.values[b] ?? 0;
                if (!v) return null;
                return <div key={b} className="w-full first:rounded-b-none last:rounded-t" style={{
                  height: `${(v / max) * 100}%`, background: bucketColor(b), opacity: c.muted ? 0.55 : 1, minHeight: 1 }} />;
              })}
            </div>
          );
        })}
      </div>
      <div className="mt-1 flex gap-1 text-[10px] text-muted">
        {columns.map((c, i) => (
          <span key={c.key} className="min-w-0 flex-1 truncate text-center">
            {columns.length > 16 && i % 2 ? "" : c.label}
          </span>
        ))}
      </div>
      <TableView head={[unit, ...shown.map((b) => BUCKET_LABEL[b]), "Total"]}
        rows={columns.map((c) => [c.label, ...shown.map((b) => hm(c.values[b] ?? 0)),
          hm(shown.reduce((s, b) => s + (c.values[b] ?? 0), 0))])} />
      {node}
    </figure>
  );
}
