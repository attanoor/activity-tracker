"use client";

import { BUCKET_LABEL, BUCKETS, bucketColor, hm } from "@/lib/viz";

import { Swatch, TableView, useTooltip } from "./Tooltip";

/** Where the shift went: one 100% bar, every bucket labelled with its time and share (adds up to the shift). */
export default function ShiftBar({ breakdown, shiftSeconds }: { breakdown: Record<string, number>; shiftSeconds: number }) {
  const { show, hide, node } = useTooltip();
  const parts = BUCKETS.map((b) => ({ b, s: breakdown[b] ?? 0 })).filter((p) => p.s > 0);
  const pct = (s: number) => (shiftSeconds ? (100 * s) / shiftSeconds : 0);
  return (
    <figure>
      <div className="flex h-7 w-full gap-[2px] overflow-hidden rounded bg-surface" role="img"
        aria-label={parts.map((p) => `${BUCKET_LABEL[p.b]} ${hm(p.s)}`).join(", ")}>
        {parts.map((p) => (
          <div key={p.b} tabIndex={0} style={{ width: `${pct(p.s)}%`, background: bucketColor(p.b), minWidth: 3 }}
            className="h-full first:rounded-l last:rounded-r focus:outline focus:outline-2 focus:outline-fg"
            onPointerMove={(e) => show(e, <><b>{BUCKET_LABEL[p.b]}</b><br />{hm(p.s)} · {pct(p.s).toFixed(0)}% of the shift</>)}
            onPointerLeave={hide} onFocus={(e) => show(e, `${BUCKET_LABEL[p.b]}: ${hm(p.s)}`)} onBlur={hide} />
        ))}
      </div>
      <ul className="mt-3 grid grid-cols-2 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-3">
        {BUCKETS.map((b) => (
          <li key={b} className={`flex items-center gap-2 ${breakdown[b] ? "" : "text-muted"}`}>
            <Swatch color={bucketColor(b)} />
            <span className="flex-1">{BUCKET_LABEL[b]}</span>
            <span className="tabular-nums">{hm(breakdown[b] ?? 0)}</span>
            <span className="w-9 text-right tabular-nums text-muted">{pct(breakdown[b] ?? 0).toFixed(0)}%</span>
          </li>
        ))}
      </ul>
      <TableView head={["Bucket", "Time", "Share"]}
        rows={[...BUCKETS.map((b) => [BUCKET_LABEL[b], hm(breakdown[b] ?? 0), `${pct(breakdown[b] ?? 0).toFixed(1)}%`]),
          ["Total", hm(shiftSeconds), "100%"]]} />
      {node}
    </figure>
  );
}
