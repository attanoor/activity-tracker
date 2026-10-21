"use client";

import { Suspense, useState } from "react";

import GoogleConnect from "@/components/GoogleConnect";
import Shell, { useUser } from "@/components/Shell";
import { api } from "@/lib/api";

function ChangePassword() {
  const user = useUser();
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const formEl = e.currentTarget;
    const form = new FormData(formEl);
    setBusy(true);
    setMsg(null);
    try {
      await api("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ current_password: form.get("current"), new_password: form.get("new") }),
      });
      formEl.reset();
      setMsg({ ok: true, text: "Password changed. Other devices were signed out." });
    } catch (err) {
      setMsg({ ok: false, text: err instanceof Error ? err.message : "Could not change the password" });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="max-w-md space-y-6">
      <h1 className="text-2xl font-semibold">Account</h1>
      <dl className="card grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
        <dt className="text-muted">Name</dt><dd>{user.name}</dd>
        <dt className="text-muted">Email</dt><dd className="break-all">{user.email}</dd>
        <dt className="text-muted">Role</dt><dd className="capitalize">{user.role}</dd>
      </dl>
      <form onSubmit={submit} className="card space-y-4">
        <h2 className="font-semibold">Change password</h2>
        {/* Hidden username lets password managers update the right saved entry. */}
        <input type="email" name="username" autoComplete="username" value={user.email} readOnly hidden />
        <div className="space-y-1">
          <label htmlFor="current-password" className="text-sm font-medium">Current password</label>
          <input id="current-password" name="current" type="password" autoComplete="current-password" required className="field" />
        </div>
        <div className="space-y-1">
          <label htmlFor="new-password" className="text-sm font-medium">New password</label>
          <input id="new-password" name="new" type="password" autoComplete="new-password" minLength={10} required
            aria-describedby="new-password-hint" enterKeyHint="done" className="field" />
          <p id="new-password-hint" className="text-xs text-muted">At least 10 characters.</p>
        </div>
        {msg && <p role={msg.ok ? "status" : "alert"} className={`text-sm ${msg.ok ? "text-ok" : "text-danger"}`}>{msg.text}</p>}
        <button type="submit" disabled={busy} className="btn-primary">{busy ? "Saving…" : "Change password"}</button>
      </form>
      <Suspense><GoogleConnect /></Suspense>
    </div>
  );
}

export default function AccountPage() {
  return (
    <Shell>
      <ChangePassword />
    </Shell>
  );
}
