"use client";

import { useCallback, useState } from "react";

export type Tip = { x: number; y: number; content: React.ReactNode } | null;

/** One floating tooltip that follows the pointer; flips left near the right edge. */
export function useTooltip() {
  const [tip, setTip] = useState<Tip>(null);
  const show = useCallback((e: React.PointerEvent | React.FocusEvent, content: React.ReactNode) => {
    const rect = (e.currentTarget as Element).getBoundingClientRect();
    const x = "clientX" in e ? e.clientX : rect.left + rect.width / 2;
    const y = "clientY" in e ? e.clientY : rect.top;
    setTip({ x, y, content });
  }, []);
  const hide = useCallback(() => setTip(null), []);
  const node = tip ? (
    <div role="tooltip" className="tooltip"
      style={{ left: Math.min(tip.x + 12, (typeof window !== "undefined" ? window.innerWidth : 9999) - 260), top: tip.y + 14 }}>
      {tip.content}
    </div>
  ) : null;
  return { show, hide, node };
}

export function Swatch({ color }: { color: string }) {
  return <span aria-hidden className="inline-block h-2.5 w-2.5 flex-none rounded-sm" style={{ background: color }} />;
}

/** Collapsible table view of a chart: the accessible and exact-numbers alternative. */
export function TableView({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <details className="mt-2 text-xs">
      <summary className="cursor-pointer text-muted">Show as table</summary>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-left tabular-nums">
          <thead className="text-muted"><tr>{head.map((h) => <th key={h} className="py-1 pr-4 font-medium">{h}</th>)}</tr></thead>
          <tbody className="divide-y divide-line">
            {rows.map((r, i) => <tr key={i}>{r.map((c, j) => <td key={j} className="py-1 pr-4">{c}</td>)}</tr>)}
          </tbody>
        </table>
      </div>
    </details>
  );
}
