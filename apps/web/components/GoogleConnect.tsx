"use client";

import { useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { api } from "@/lib/api";

type Status = { mode: string; connected: boolean; google_email: string | null; identity: string; sources: string[] };
const SOURCE: Record<string, string> = { calendar: "Calendar meetings", gmail: "Gmail counts (headers only)", drive: "Drive activity" };

export default function GoogleConnect() {
  const params = useSearchParams();
  const [s, setS] = useState<Status | null>(null);
  const load = () => api<Status>("/integrations/google/status").then(setS).catch(() => setS(null));
  useEffect(() => { load(); }, []);
  if (!s) return null;
  const result = params.get("google");

  return (
    <section className="card space-y-3" aria-labelledby="h-google">
      <h2 id="h-google" className="font-semibold">Google account</h2>
      {result === "connected" && <p role="status" className="text-sm text-ok">Google is connected.</p>}
      {result === "error" && <p role="alert" className="text-sm text-danger">Google sign-in failed: {params.get("reason")}</p>}
      {s.mode === "off" && <p className="text-sm text-muted">Google integration is switched off by your admin.</p>}
      {s.mode === "service_account" && (
        <p className="text-sm">Connected by your admin for <b>{s.identity}</b>. Nothing to do here.</p>
      )}
      {s.mode === "oauth" && (
        s.connected ? (
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <span>Connected as <b>{s.google_email}</b></span>
            <button className="btn-secondary" onClick={async () => { await api("/integrations/google/disconnect", { method: "POST" }); load(); }}>Disconnect</button>
          </div>
        ) : <a className="btn-primary" href="/api/integrations/google/connect">Connect Google</a>
      )}
      {s.mode !== "off" && (
        <p className="text-xs text-muted">Read-only: {s.sources.map((x) => SOURCE[x]).join(", ")}. Email bodies are never read.</p>
      )}
    </section>
  );
}
