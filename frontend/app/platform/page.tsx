"use client";

import { useCallback, useEffect, useState } from "react";
import { API_BASE } from "../cashflow/lib";
import { Badge, Card, GhostButton, inputClass } from "../cashflow/ui";

const TKEY = "nf_platform_token";
type Ws = { id: string; name: string; starts_with: "empty" | "sample"; status: "active" | "suspended"; created_at: number; keys: number; last_active: number | null; datasets: number };
type KeyRow = { id: string; role: "admin" | "viewer"; label: string; created_at: number; last_used_at: number | null; revoked: boolean };
type Issued = { wsId: string; wsName: string; role: string; label: string; key: string };

const when = (t?: number | null) => (t ? new Date(t * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "never");
const getTok = () => { try { return sessionStorage.getItem(TKEY) || ""; } catch { return ""; } };
const setTok = (t: string) => { try { if (t) sessionStorage.setItem(TKEY, t); else sessionStorage.removeItem(TKEY); } catch { /* lives until reload */ } };

async function api<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}/platform${path}`, {
    method,
    headers: { "X-Platform-Token": getTok(), ...(body !== undefined ? { "Content-Type": "application/json" } : {}) },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    let msg = `Request failed (${res.status}).`;
    try { const j = await res.json(); if (typeof j?.detail === "string") msg = j.detail; } catch { /* generic */ }
    throw Object.assign(new Error(msg), { status: res.status });
  }
  return res.json();
}

function KeyManager({ ws, onIssued, onChanged, setError }: { ws: Ws; onIssued: (i: Issued) => void; onChanged: () => void; setError: (m: string | null) => void }) {
  const [keys, setKeys] = useState<KeyRow[]>([]);
  const [role, setRole] = useState<"admin" | "viewer">("viewer");
  const [label, setLabel] = useState("");
  const load = useCallback(() => api<{ keys: KeyRow[] }>("GET", `/workspaces/${ws.id}/keys`).then((r) => setKeys(r.keys)).catch((e: Error) => setError(e.message)), [ws.id, setError]);
  useEffect(() => { load(); }, [load]);
  async function issue() {
    setError(null);
    try {
      const r = await api<{ key: string; role: string; label: string }>("POST", `/workspaces/${ws.id}/keys`, { role, label });
      onIssued({ wsId: ws.id, wsName: ws.name, role: r.role, label: r.label, key: r.key });
      setLabel("");
      load();
      onChanged();
    } catch (e) { setError((e as Error).message); }
  }
  async function revoke(k: KeyRow) {
    if (!window.confirm(`Revoke the ${k.role} key "${k.label || k.id}"? It stops working immediately.`)) return;
    setError(null);
    try { await api("DELETE", `/workspaces/${ws.id}/keys/${k.id}`); load(); onChanged(); } catch (e) { setError((e as Error).message); }
  }
  return (
    <div className="mt-3 space-y-2">
      <ul className="m-0 list-none space-y-1 p-0">
        {keys.map((k) => (
          <li key={k.id} className="flex flex-wrap items-center justify-between gap-2 text-xs text-[#d1d5db]" data-testid={`key-${k.id}`}>
            <span>
              <Badge tone={k.revoked ? "bad" : k.role === "admin" ? "blue" : "neutral"}>{k.revoked ? "Revoked" : k.role}</Badge> {k.label || k.id} · used {when(k.last_used_at)}
            </span>
            {!k.revoked && <GhostButton danger onClick={() => revoke(k)}>Revoke</GhostButton>}
          </li>
        ))}
      </ul>
      <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); issue(); }}>
        <select aria-label="Key role" className={`${inputClass} w-auto`} value={role} onChange={(e) => setRole(e.target.value as "admin" | "viewer")}>
          <option value="viewer">Viewer (read only)</option>
          <option value="admin">Admin (connects data)</option>
        </select>
        <input aria-label="Key label" className={`${inputClass} w-48`} placeholder="Who is this for?" value={label} onChange={(e) => setLabel(e.target.value)} />
        <button type="submit" className="rounded-lg border border-[#374151] px-3 py-1.5 text-xs font-semibold text-[#e5e7eb] hover:border-[#60a5fa]">Issue key</button>
      </form>
    </div>
  );
}

export default function PlatformPage() {
  const [token, setToken] = useState("");
  const [authed, setAuthed] = useState(false);
  const [list, setList] = useState<Ws[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [issued, setIssued] = useState<Issued | null>(null);
  const [name, setName] = useState("");
  const [startsWith, setStartsWith] = useState<"empty" | "sample">("empty");
  const [open, setOpen] = useState<string | null>(null);
  const [copied, setCopied] = useState(false);

  const load = useCallback(async () => {
    try {
      const r = await api<{ workspaces: Ws[] }>("GET", "/workspaces");
      setList(r.workspaces);
      setAuthed(true);
    } catch (e) {
      const st = (e as { status?: number }).status;
      if (st === 401) { setTok(""); setAuthed(false); }
      setError(st === 401 ? (getTok() ? "That token was not accepted." : null) : (e as Error).message);
    }
  }, []);
  useEffect(() => { if (getTok()) Promise.resolve().then(load); }, [load]);

  async function unlock() {
    setError(null);
    setTok(token.trim());
    try { await api("GET", "/workspaces"); setToken(""); await load(); } catch (e) { setTok(""); setError((e as Error).message); }
  }
  async function create() {
    setError(null);
    try {
      const r = await api<{ workspace: Ws; key: { key: string } }>("POST", "/workspaces", { name, starts_with: startsWith });
      setIssued({ wsId: r.workspace.id, wsName: r.workspace.name, role: "admin", label: "First admin key", key: r.key.key });
      setName("");
      await load();
    } catch (e) { setError((e as Error).message); }
  }
  async function setStatus(w: Ws, status: "active" | "suspended") {
    setError(null);
    try { await api("PATCH", `/workspaces/${w.id}`, { status }); await load(); } catch (e) { setError((e as Error).message); }
  }
  async function remove(w: Ws) {
    const typed = window.prompt(`This permanently deletes ${w.name}: its data, uploads, saved connections, models and keys. Type the workspace name to confirm.`);
    if (typed !== w.name) return;
    setError(null);
    try { await api("DELETE", `/workspaces/${w.id}`); setOpen(null); await load(); } catch (e) { setError((e as Error).message); }
  }

  const link = issued && typeof window !== "undefined" ? `${window.location.origin}/signin#key=${issued.key}` : "";
  async function copy(text: string) {
    try { await navigator.clipboard.writeText(text); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* select and copy by hand */ }
  }

  return (
    <main className="mx-auto w-full min-w-0 max-w-[1000px] space-y-5 px-4 py-6 text-[#e5e7eb] sm:px-6">
      <header>
        <h1 className="m-0 text-2xl font-semibold">Customer workspaces</h1>
        <p className="mt-1 max-w-2xl text-sm text-[#9ca3af]">Each customer gets a private workspace with its own data, connections and models. You create it and send them a key; they cannot see anyone else&apos;s.</p>
      </header>
      {error && <p role="alert" className="rounded-xl border border-[#7f1d1d] bg-[#2a0f12] px-4 py-3 text-sm text-[#fca5a5]">{error}</p>}

      {!authed && (
        <Card title="Platform token">
          <p className="mt-0 text-sm text-[#9ca3af]">Enter the platform admin token (<code>PLATFORM_ADMIN_TOKEN</code> on the server). It is kept for this browser tab only.</p>
          <form className="flex max-w-md gap-2" onSubmit={(e) => { e.preventDefault(); unlock(); }}>
            <input type="password" aria-label="Platform token" autoComplete="off" className={inputClass} value={token} onChange={(e) => setToken(e.target.value)} />
            <button type="submit" disabled={!token.trim()} className="rounded-lg bg-[#2563eb] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-50">Unlock</button>
          </form>
        </Card>
      )}

      {authed && issued && (
        <section role="status" className="rounded-2xl border border-[#065f46] bg-[#052e22] p-4 text-sm text-[#d1fae5]" data-testid="issued-key">
          <p className="m-0 font-semibold">New {issued.role} key for {issued.wsName}{issued.label ? ` (${issued.label})` : ""}</p>
          <p className="mb-2 mt-1 text-xs">This is the only time the key is shown. Copy it now and send it privately. If it is lost, issue a new one.</p>
          <code className="block break-all rounded-lg bg-[#0b0b0f] p-2 text-xs" data-testid="issued-key-value">{issued.key}</code>
          <div className="mt-2 flex flex-wrap gap-2">
            <GhostButton onClick={() => copy(issued.key)}>{copied ? "Copied" : "Copy key"}</GhostButton>
            <GhostButton onClick={() => copy(link)}>Copy private sign-in link</GhostButton>
            <GhostButton onClick={() => setIssued(null)}>I have saved it</GhostButton>
          </div>
        </section>
      )}

      {authed && (
        <>
          <Card title="New workspace">
            <form className="flex flex-wrap items-end gap-3" onSubmit={(e) => { e.preventDefault(); create(); }}>
              <label className="text-sm">Company name
                <input className={`${inputClass} mt-1 w-64`} value={name} onChange={(e) => setName(e.target.value)} placeholder="Acme Industrial" />
              </label>
              <label className="text-sm">Starts with
                <select className={`${inputClass} mt-1 w-64`} value={startsWith} onChange={(e) => setStartsWith(e.target.value as "empty" | "sample")}>
                  <option value="empty">Empty: they connect their own data</option>
                  <option value="sample">Demo: labelled sample data</option>
                </select>
              </label>
              <button type="submit" disabled={!name.trim()} className="rounded-lg bg-[#2563eb] px-3 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-50">Create workspace</button>
            </form>
          </Card>

          <Card title={`Workspaces${list ? ` (${list.length})` : ""}`}>
            {list && list.length === 0 && <p className="m-0 text-sm text-[#9ca3af]">None yet. Create the first one above.</p>}
            <ul className="m-0 list-none space-y-3 p-0">
              {(list ?? []).map((w) => (
                <li key={w.id} className="rounded-xl border border-[#1f2937] p-4" data-testid={`ws-${w.id}`}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="m-0 text-sm font-semibold">{w.name}</h3>
                        <Badge tone={w.status === "active" ? "good" : "warn"}>{w.status === "active" ? "Active" : "Suspended"}</Badge>
                        {w.starts_with === "sample" && <Badge tone="warn">Demo data</Badge>}
                      </div>
                      <p className="m-0 mt-1 text-xs text-[#9ca3af]">{w.id} · {w.keys} active key{w.keys === 1 ? "" : "s"} · {w.datasets} dataset{w.datasets === 1 ? "" : "s"} connected · last active {when(w.last_active)}</p>
                    </div>
                    <div className="flex flex-wrap gap-2">
                      <GhostButton onClick={() => setOpen(open === w.id ? null : w.id)}>{open === w.id ? "Hide keys" : "Keys"}</GhostButton>
                      {w.status === "active" ? <GhostButton onClick={() => setStatus(w, "suspended")}>Suspend</GhostButton> : <GhostButton onClick={() => setStatus(w, "active")}>Resume</GhostButton>}
                      <GhostButton danger onClick={() => remove(w)}>Delete</GhostButton>
                    </div>
                  </div>
                  {open === w.id && <KeyManager ws={w} onIssued={setIssued} onChanged={load} setError={setError} />}
                </li>
              ))}
            </ul>
          </Card>
        </>
      )}
    </main>
  );
}
