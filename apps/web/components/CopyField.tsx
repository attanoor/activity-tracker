"use client";

import { useRef, useState } from "react";

/** A read-only value with a Copy button. Falls back to selecting the text where the clipboard API is blocked (plain HTTP). */
export default function CopyField({ label, value, mono = true }: { label: string; value: string; mono?: boolean }) {
  const ref = useRef<HTMLInputElement>(null);
  const [note, setNote] = useState("");
  const id = `copy-${label.replace(/\W+/g, "-").toLowerCase()}`;

  async function copy() {
    try {
      await navigator.clipboard.writeText(value);
      setNote("Copied");
    } catch {
      ref.current?.select();
      setNote("Selected: press Ctrl+C");
    }
  }

  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-sm font-medium">{label}</label>
      <div className="flex gap-2">
        <input id={id} ref={ref} readOnly value={value} onFocus={(e) => e.currentTarget.select()}
          className={`field ${mono ? "font-mono tracking-wide" : ""}`} />
        <button type="button" onClick={copy} className="btn-secondary">Copy</button>
      </div>
      <p role="status" className="min-h-4 text-xs text-ok">{note}</p>
    </div>
  );
}
