"use client";

import { useState } from "react";
import { API_BASE } from "../cashflow/lib";

export default function DemoForm() {
  const [v, setV] = useState({ name: "", email: "", company: "", message: "", website: "" });
  const [state, setState] = useState<"idle" | "busy" | "done">("idle");
  const [error, setError] = useState<string | null>(null);
  const set = (k: keyof typeof v, val: string) => setV((p) => ({ ...p, [k]: val }));

  async function submit() {
    setError(null);
    setState("busy");
    try {
      const res = await fetch(`${API_BASE}/public/demo-request`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(v) });
      const j = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(typeof j?.detail === "string" ? j.detail : "Check the form: a name and a valid email are needed.");
      setState("done");
    } catch (e) {
      setError((e as Error).message === "Failed to fetch" ? "Couldn't reach the server. Check your connection and try again." : (e as Error).message);
      setState("idle");
    }
  }

  if (state === "done") {
    return (
      <p role="status" className="m-0 max-w-xl text-lg" data-testid="demo-done">
        Thanks, {v.name.split(" ")[0]}. We&apos;ll reply to {v.email} to set up a walkthrough on your kind of data.
      </p>
    );
  }
  return (
    <form className="grid max-w-xl gap-4" onSubmit={(e) => { e.preventDefault(); submit(); }}>
      <div className="grid gap-4 sm:grid-cols-2">
        <div><label htmlFor="d-name">Your name</label><input id="d-name" required maxLength={100} value={v.name} onChange={(e) => set("name", e.target.value)} autoComplete="name" /></div>
        <div><label htmlFor="d-email">Work email</label><input id="d-email" type="email" required maxLength={320} value={v.email} onChange={(e) => set("email", e.target.value)} autoComplete="email" /></div>
      </div>
      <div><label htmlFor="d-co">Company</label><input id="d-co" maxLength={120} value={v.company} onChange={(e) => set("company", e.target.value)} autoComplete="organization" /></div>
      <div><label htmlFor="d-msg">What would you like to see?</label><textarea id="d-msg" rows={4} maxLength={1000} value={v.message} onChange={(e) => set("message", e.target.value)} placeholder="For example: our invoices live in Snowflake and we want to know which customers to watch." /></div>
      {/* Spam trap: hidden from people, so only automated forms fill it in. */}
      <div aria-hidden className="absolute left-[-9999px] h-0 w-0 overflow-hidden"><label htmlFor="d-site">Website</label><input id="d-site" tabIndex={-1} autoComplete="off" value={v.website} onChange={(e) => set("website", e.target.value)} /></div>
      {error && <p role="alert" className="m-0 text-[var(--red)]">{error}</p>}
      <div className="flex flex-wrap items-center gap-4">
        <button type="submit" className="btn" disabled={state === "busy"}>{state === "busy" ? "Sending…" : "Request a demo"}</button>
        <p className="m-0 max-w-sm text-sm text-[var(--muted)]">We use your details only to reply about NeuraFlow.</p>
      </div>
    </form>
  );
}
