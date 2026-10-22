"use client";

import { useEffect, useRef, useState } from "react";

import Shell from "@/components/Shell";
import { api } from "@/lib/api";

type Download = { key: "agent" | "extension"; file: string; version: string; size: number; sha256: string; built_at: string };
type Code = { code: string; expires_at: string };

const mb = (n: number) => `${(n / 1024 / 1024).toFixed(1)} MB`;
const kb = (n: number) => `${Math.max(1, Math.round(n / 1024))} KB`;

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <section className="card" aria-labelledby={`step-${n}`}>
      <div className="flex gap-4">
        <span aria-hidden className="grid h-8 w-8 flex-none place-items-center rounded-full bg-accent text-sm font-bold text-accent-fg">{n}</span>
        <div className="min-w-0 flex-1 space-y-3">
          <h2 id={`step-${n}`} className="text-lg font-semibold">{title}</h2>
          {children}
        </div>
      </div>
    </section>
  );
}

function FileButton({ d, label }: { d?: Download; label: string }) {
  if (!d) return <p className="text-sm text-danger" role="status">Not built yet. An admin needs to run scripts\build-downloads.ps1.</p>;
  return (
    <div className="space-y-2">
      <div className="flex flex-wrap items-center gap-3">
        <a href={`/api/downloads/${d.key}`} download={d.file} className="btn-primary">{label}</a>
        <span className="text-sm text-muted">
          {d.file} · version {d.version} · {d.key === "agent" ? mb(d.size) : kb(d.size)}
        </span>
      </div>
      <details className="text-xs text-muted">
        <summary className="cursor-pointer">File checksum (SHA-256)</summary>
        <code className="mt-1 block break-all font-mono">{d.sha256}</code>
      </details>
    </div>
  );
}

function SetupCode() {
  const [code, setCode] = useState<Code | null>(null);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState("");
  const input = useRef<HTMLInputElement>(null);

  async function generate() {
    setError("");
    setCopied("");
    try {
      setCode(await api<Code>("/me/enrol-codes", { method: "POST" }));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not create a code");
    }
  }

  async function copy() {
    if (!code) return;
    try {
      await navigator.clipboard.writeText(code.code);
      setCopied("Copied");
    } catch {
      // The clipboard API needs HTTPS (or localhost); select the code so Ctrl+C works instead.
      input.current?.select();
      setCopied("Selected: press Ctrl+C to copy");
    }
  }

  return (
    <div className="space-y-3">
      <p className="text-sm text-muted">
        The agent asks for this code the first time it runs. It links that PC to your account, works once, and
        expires after 7 days. Make a new one for each PC.
      </p>
      {code ? (
        <div className="flex flex-wrap items-center gap-3">
          <label htmlFor="setup-code" className="sr-only">Setup code</label>
          <input id="setup-code" ref={input} readOnly value={code.code} onFocus={(e) => e.currentTarget.select()}
            className="field w-auto min-w-0 font-mono text-xl tracking-widest" size={16} />
          <button onClick={copy} className="btn-secondary">Copy</button>
          <span role="status" className="text-sm text-ok">{copied}</span>
          <p className="basis-full text-xs text-muted">
            Expires {new Date(code.expires_at).toLocaleString()}.{" "}
            <button onClick={generate} className="underline underline-offset-2">Make another</button>
          </p>
        </div>
      ) : (
        <button onClick={generate} className="btn-primary">Get my setup code</button>
      )}
      {error && <p role="alert" className="text-sm text-danger">{error}</p>}
    </div>
  );
}

function DownloadsPage() {
  const [files, setFiles] = useState<Download[] | null>(null);
  const [origin, setOrigin] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    setOrigin(window.location.origin);
    api<Download[]>("/downloads").then(setFiles).catch(() => setFiles([]));
    api<{ text: string }>("/privacy-notice").then((r) => setNotice(r.text)).catch(() => undefined);
  }, []);

  const agent = files?.find((f) => f.key === "agent");
  const ext = files?.find((f) => f.key === "extension");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Set up tracking on your PC</h1>
        <p className="mt-1 max-w-3xl text-muted">
          Three steps, about five minutes. The agent shows a tray icon whenever it runs, and you can pause it or
          switch to Private mode at any time. You review your daily report before your manager sees it.
        </p>
      </div>

      <Step n={1} title="Get your setup code">
        <SetupCode />
      </Step>

      <Step n={2} title="Install the Windows agent">
        {files === null ? <p className="text-sm text-muted" role="status">Loading…</p> : <FileButton d={agent} label="Download agent for Windows" />}
        <ol className="list-decimal space-y-1 pl-5 text-sm">
          <li>Run <strong>ActivityTrackerAgent.exe</strong>. No installation or admin rights needed.</li>
          <li>
            If Windows shows <em>“Windows protected your PC”</em>, click <strong>More info → Run anyway</strong>.
            The agent is not code-signed yet; the checksum above lets you confirm the file is the one published here.
          </li>
          <li>
            In the setup window, keep the server address as <code className="font-mono">{origin || "this site's address"}</code>,
            enter your setup code and click <strong>Connect</strong>.
          </li>
          <li>A green <strong>T</strong> icon appears in the tray. Right-click it to pause, use Private mode or see the status.</li>
        </ol>
        <p className="text-xs text-muted">The agent starts with Windows from then on. You can turn that off in its tray menu.</p>
      </Step>

      <Step n={3} title="Add the browser extension">
        {files === null ? null : <FileButton d={ext} label="Download extension" />}
        <p className="text-sm text-muted">
          Without it the agent still sees the browser's window title. With it, the exact site is recorded, so the
          report can say which ticket or document you worked on.
        </p>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <h3 className="font-medium">Google Chrome</h3>
            <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm">
              <li>Unzip the download to a folder you will keep, for example Documents.</li>
              <li>Open <code className="font-mono">chrome://extensions</code> in the address bar.</li>
              <li>Turn on <strong>Developer mode</strong> (top right).</li>
              <li>Click <strong>Load unpacked</strong> and choose the <code className="font-mono">activity-tracker-extension</code> folder.</li>
            </ol>
          </div>
          <div>
            <h3 className="font-medium">Microsoft Edge</h3>
            <ol className="mt-1 list-decimal space-y-1 pl-5 text-sm">
              <li>Unzip the download to a folder you will keep.</li>
              <li>Open <code className="font-mono">edge://extensions</code>.</li>
              <li>Turn on <strong>Developer mode</strong> (left side).</li>
              <li>Click <strong>Load unpacked</strong> and choose the <code className="font-mono">activity-tracker-extension</code> folder.</li>
            </ol>
          </div>
        </div>
        <p className="text-xs text-muted">
          The extension icon shows no badge when tracking, <strong>II</strong> when paused, <strong>P</strong> in
          Private mode and <strong>!</strong> if the agent is not running. Incognito/InPrivate windows are never reported.
        </p>
      </Step>

      <section className="card" aria-labelledby="privacy">
        <h2 id="privacy" className="text-lg font-semibold">What is recorded</h2>
        {notice && <p className="mt-2 whitespace-pre-line text-sm">{notice}</p>}
        <div className="mt-3 grid gap-4 text-sm sm:grid-cols-2">
          <div>
            <h3 className="font-medium text-ok">Recorded</h3>
            <ul className="mt-1 list-disc space-y-1 pl-5">
              <li>The app and window title in front, and for how long</li>
              <li>The site and page title of the active browser tab</li>
              <li>On work sites, what the page is about: its headings, menu path and the club name shown, so time
                can be put against the right client</li>
              <li>Idle time (no keyboard or mouse for 5 minutes) and when the PC is locked</li>
            </ul>
          </div>
          <div>
            <h3 className="font-medium text-danger">Never recorded</h3>
            <ul className="mt-1 list-disc space-y-1 pl-5">
              <li>Screenshots, keystrokes or the clipboard</li>
              <li>What you type into any field, email bodies, page contents, or anything in incognito/InPrivate windows</li>
              <li>Any detail while paused or in Private mode, beyond the time itself</li>
            </ul>
          </div>
        </div>
      </section>
    </div>
  );
}

export default function Page() {
  return (
    <Shell>
      <DownloadsPage />
    </Shell>
  );
}
