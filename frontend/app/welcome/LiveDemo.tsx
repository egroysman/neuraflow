"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { API_BASE } from "../cashflow/lib";
import { setKey } from "../auth";

/** Opens the shared read-only demo workspace (sample data) without asking for a key. */
export default function LiveDemo() {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  async function open() {
    setBusy(true);
    setError(null);
    try {
      const res = await fetch(`${API_BASE}/public/demo-access`);
      if (!res.ok) throw new Error("The live demo isn't available right now.");
      setKey((await res.json()).key, false);
      router.push("/cashflow");
    } catch (e) {
      setError((e as Error).message);
      setBusy(false);
    }
  }
  return (
    <span>
      <button type="button" className="btn btn-quiet" onClick={open} disabled={busy}>{busy ? "Opening…" : "Try the live demo"}</button>
      {error && <span role="alert" className="ml-3 text-sm text-[var(--red)]">{error}</span>}
    </span>
  );
}
