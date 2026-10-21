"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { api } from "@/lib/api";

function LoginForm() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [show, setShow] = useState(false);

  async function submit(e: React.FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    setBusy(true);
    setError("");
    try {
      await api("/auth/login", {
        method: "POST",
        body: JSON.stringify({ email: form.get("email"), password: form.get("password") }),
      });
      const next = params.get("next");
      router.replace(next?.startsWith("/") && !next.startsWith("//") ? next : "/day");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Sign-in failed");
      setBusy(false);
    }
  }

  return (
    <form onSubmit={submit} className="card w-full max-w-sm space-y-4" aria-describedby={error ? "login-error" : undefined}>
      <div>
        <h1 className="text-xl font-semibold">Sign in</h1>
        <p className="mt-1 text-sm text-muted">Activity Tracker</p>
      </div>
      <div className="space-y-1">
        <label htmlFor="email" className="text-sm font-medium">Email</label>
        <input id="email" name="email" type="email" autoComplete="username" spellCheck={false} enterKeyHint="next"
          required autoFocus className="field" />
      </div>
      <div className="space-y-1">
        <div className="flex items-center justify-between">
          <label htmlFor="current-password" className="text-sm font-medium">Password</label>
          <button type="button" onClick={() => setShow((s) => !s)} aria-controls="current-password"
            className="text-xs text-muted underline-offset-2 hover:underline">
            {show ? "Hide password" : "Show password"}
          </button>
        </div>
        <input id="current-password" name="password" type={show ? "text" : "password"} autoComplete="current-password"
          enterKeyHint="done" required className="field" />
        <p className="text-xs text-muted">Forgot it? Ask your admin to reset it.</p>
      </div>
      {error && <p id="login-error" role="alert" className="text-sm text-danger">{error}</p>}
      <button type="submit" disabled={busy} className="btn-primary w-full">{busy ? "Signing in…" : "Sign in"}</button>
    </form>
  );
}

export default function LoginPage() {
  return (
    <main className="grid min-h-dvh place-items-center px-4">
      <Suspense>
        <LoginForm />
      </Suspense>
    </main>
  );
}
