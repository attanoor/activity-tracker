"use client";

import { useEffect, useRef } from "react";

/** Native modal <dialog>: focus trapping, Esc to close and the backdrop come from the browser. */
export default function Modal({ open, title, onClose, children }: {
  open: boolean; title: string; onClose: () => void; children: React.ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);
  return (
    <dialog ref={ref} onClose={onClose} aria-labelledby="modal-title"
      className="w-[min(32rem,calc(100vw-2rem))] rounded-xl border border-line bg-surface p-0 text-fg backdrop:bg-black/40">
      {open && (
        <div className="p-5 sm:p-6">
          <div className="mb-4 flex items-start justify-between gap-4">
            <h2 id="modal-title" className="text-lg font-semibold">{title}</h2>
            <button type="button" onClick={onClose} aria-label="Close" className="btn-secondary px-2 py-1">✕</button>
          </div>
          {children}
        </div>
      )}
    </dialog>
  );
}
