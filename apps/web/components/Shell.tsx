"use client";

import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";

import { api, ApiError, type User } from "@/lib/api";

const UserContext = createContext<User | null>(null);
export const useUser = () => useContext(UserContext)!;

const NAV = [
  { href: "/day", label: "My day" },
  { href: "/analysis", label: "Analysis" },
  { href: "/downloads", label: "Downloads" },
  { href: "/account", label: "Account" },
];

/** Signed-in layout: loads the current user, or sends the visitor to /login and back afterwards. */
export default function Shell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    api<User>("/auth/me")
      .then(setUser)
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.replace(`/login?next=${encodeURIComponent(pathname)}`);
      });
  }, [router, pathname]);

  async function signOut() {
    await api("/auth/logout", { method: "POST" });
    router.replace("/login");
  }

  if (!user) return <p className="p-6 text-muted" role="status">Loading…</p>;

  return (
    <UserContext.Provider value={user}>
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Link href="/day" className="flex items-center gap-2 font-semibold">
            <span aria-hidden className="grid h-7 w-7 place-items-center rounded-full bg-accent text-sm text-accent-fg">T</span>
            Activity Tracker
          </Link>
          <nav aria-label="Main" className="flex flex-wrap gap-1">
            {[...NAV.slice(0, 2), ...(user.role !== "resource" ? [{ href: "/team", label: "Team" }] : []), ...NAV.slice(2),
              ...(user.role === "admin" ? [{ href: "/admin", label: "Admin" }] : [])].map((n) => (
              <Link key={n.href} href={n.href} aria-current={pathname === n.href || pathname.startsWith(n.href + "/") ? "page" : undefined}
                className="rounded-md px-3 py-1.5 text-sm text-muted hover:text-fg aria-[current=page]:bg-bg aria-[current=page]:text-fg">
                {n.label}
              </Link>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="text-muted">
              {user.name} <span className="rounded bg-bg px-1.5 py-0.5 text-xs capitalize">{user.role}</span>
            </span>
            <button onClick={signOut} className="btn-secondary px-3 py-1.5">Sign out</button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-6xl px-4 py-8">{children}</main>
    </UserContext.Provider>
  );
}
