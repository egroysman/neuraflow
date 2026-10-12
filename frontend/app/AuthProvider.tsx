"use client";

import { usePathname, useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useState } from "react";
import Link from "next/link";
import { API_BASE } from "./cashflow/lib";
import { authFetch, checkKey, fetchMode, getKey, onAuthChange, setKey, type Session } from "./auth";

export type Status = { mode: "sample" | "custom"; empty?: boolean };
type Ctx = { ready: boolean; required: boolean; session: Session | null; status: Status | null; signOut: () => void };

const AuthCtx = createContext<Ctx>({ ready: false, required: false, session: null, status: null, signOut: () => {} });
export const useAuth = () => useContext(AuthCtx);

const OPEN_PATHS = ["/welcome", "/signin", "/platform"];

function EmptyState({ admin, name }: { admin: boolean; name?: string }) {
  return (
    <main className="mx-auto flex w-full max-w-xl flex-1 flex-col items-center justify-center px-4 py-16 text-center text-[#e5e7eb]" data-testid="empty-state">
      <h1 className="m-0 text-2xl font-semibold">Connect your data</h1>
      <p className="mt-3 text-sm text-[#9ca3af]">
        {name ? `${name} has` : "This workspace has"} no data yet, so there is nothing to forecast or score. Upload a file, or connect Snowflake, Databricks or an SFTP folder. Nothing here is filled in with sample numbers.
      </p>
      {admin ? (
        <Link href="/data" className="mt-5 rounded-lg bg-[#2563eb] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8]">Connect your data</Link>
      ) : (
        <p className="mt-5 rounded-lg border border-[#374151] px-4 py-2 text-sm text-[#d1d5db]">Ask your workspace administrator to connect the data. Your key can view results but not change data.</p>
      )}
    </main>
  );
}

export default function AuthProvider({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [required, setRequired] = useState(false);
  const [session, setSession] = useState<Session | null>(null);
  const [status, setStatus] = useState<Status | null>(null);
  const [tick, setTick] = useState(0);

  // A private link (…/signin#key=…) signs in without typing. Keep the key out of the address bar afterwards.
  useEffect(() => {
    const m = /(?:^|[#&])key=([^&]+)/.exec(window.location.hash);
    if (m) {
      setKey(decodeURIComponent(m[1]), false);
      window.history.replaceState(null, "", window.location.pathname + window.location.search);
    }
  }, []);

  useEffect(() => onAuthChange(() => setTick((t) => t + 1)), []);

  useEffect(() => {
    let alive = true;
    (async () => {
      let req = false;
      try {
        const m = await fetchMode();
        req = m.login_required ?? m.mode === "required";
      } catch {
        /* server unreachable: pages show their own errors */
      }
      let s: Session | null = null;
      if (req || getKey()) {
        try {
          s = await checkKey(getKey());
        } catch {
          if (getKey()) setKey("");
        }
      } else {
        try {
          s = await checkKey("");
        } catch {
          /* ignore */
        }
      }
      if (!alive) return;
      setRequired(req);
      setSession(s);
      setReady(true);
    })();
    return () => {
      alive = false;
    };
  }, [tick]);

  const loadStatus = useCallback(() => {
    if (!session) return;
    authFetch(`${API_BASE}/data/status`)
      .then((r) => (r.ok ? r.json() : null))
      .then((j) => setStatus(j ? { mode: j.mode, empty: !!j.empty } : null))
      .catch(() => {});
  }, [session]);
  useEffect(() => {
    loadStatus();
    window.addEventListener("nf-data-changed", loadStatus); // the Data page fires this after it loads or removes data
    return () => window.removeEventListener("nf-data-changed", loadStatus);
  }, [loadStatus]);

  const open = OPEN_PATHS.some((p) => path.startsWith(p));
  useEffect(() => {
    if (ready && required && !session && !open) router.replace(path === "/" ? "/welcome" : "/signin");
  }, [ready, required, session, open, path, router]);

  useEffect(() => {
    if (ready && session && path.startsWith("/signin")) router.replace("/cashflow");
  }, [ready, session, path, router]);

  const signOut = useCallback(() => {
    setKey("");
    router.replace("/signin");
  }, [router]);

  return <AuthCtx.Provider value={{ ready, required, session, status: session ? status : null, signOut }}>{children}</AuthCtx.Provider>;
}

/** Wraps the page content (not the nav): holds back pages until the person is signed in, and shows
 *  the connect-your-data screen for a workspace that has no data yet. */
export function AuthGate({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const { ready, required, session, status } = useAuth();
  const open = OPEN_PATHS.some((p) => path.startsWith(p));
  if (!ready && !open) return <p role="status" className="p-6 text-sm text-[#9ca3af]">Loading…</p>;
  if (ready && required && !session && !open) return null;
  if (session && status?.empty && (path.startsWith("/cashflow") || path.startsWith("/models"))) return <EmptyState admin={session.role === "admin"} name={session.name} />;
  return <>{children}</>;
}
