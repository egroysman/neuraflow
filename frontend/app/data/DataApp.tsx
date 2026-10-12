"use client";

import { useEffect, useState } from "react";
import { Badge, Card, GhostButton, Stat, inputClass } from "../cashflow/ui";
import { ApiError, getStatus, ghostScan, listConnections, refreshDataset, resetAll, resetDataset, setToken } from "./api";
import ConnectionsCard from "./ConnectionsCard";
import Wizard from "./Wizard";
import type { Connection, DataStatus, DatasetStatus, Schedule } from "./types";

const when = (t?: number | null) => (t ? new Date(t * 1000).toLocaleString([], { dateStyle: "medium", timeStyle: "short" }) : "");

function scheduleText(s?: Schedule): string {
  if (!s || s.mode === "off") return "Refreshes only when you ask";
  if (s.mode === "interval") return `Refreshes every ${s.every_minutes} min`;
  return `Refreshes daily at ${s.at}${s.timezone ? ` (${s.timezone})` : ""}`;
}

type Access = "loading" | "ok" | "needs-token" | "disabled";

async function loadAll(): Promise<{ status: DataStatus; conns: Connection[]; encryption: boolean; access: Access }> {
  const status = await getStatus();
  if (!status.admin.enabled) return { status, conns: [], encryption: status.encryption_ready, access: "disabled" };
  try {
    const c = await listConnections();
    return { status, conns: c.connections, encryption: c.encryption_ready, access: "ok" };
  } catch (e) {
    if (e instanceof ApiError && (e.status === 401 || e.status === 429)) return { status, conns: [], encryption: status.encryption_ready, access: "needs-token" };
    throw e;
  }
}

export default function DataApp() {
  const [status, setStatus] = useState<DataStatus | null>(null);
  const [conns, setConns] = useState<Connection[]>([]);
  const [encryption, setEncryption] = useState(false);
  const [access, setAccess] = useState<Access>("loading");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [wizard, setWizard] = useState<DatasetStatus | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [tokenText, setTokenText] = useState("");
  const [tokenError, setTokenError] = useState<string | null>(null);

  function apply(r: Awaited<ReturnType<typeof loadAll>>) {
    setStatus(r.status);
    setConns(r.conns);
    setEncryption(r.encryption);
    setAccess(r.access);
  }
  async function reload() {
    try {
      apply(await loadAll());
      window.dispatchEvent(new Event("nf-data-changed"));
    } catch (e) {
      setError((e as Error).message);
    }
  }

  useEffect(() => {
    let alive = true;
    loadAll()
      .then((r) => alive && apply(r))
      .catch((e: Error) => alive && setError(e.message || "Could not load."));
    return () => {
      alive = false;
    };
  }, []);

  async function submitToken() {
    setTokenError(null);
    setToken(tokenText.trim());
    try {
      const r = await loadAll();
      if (r.access === "needs-token") {
        setToken("");
        setTokenError("That token was not accepted.");
        return;
      }
      setTokenText("");
      apply(r);
    } catch (e) {
      setTokenError((e as Error).message);
    }
  }

  async function act(id: string, fn: () => Promise<unknown>, done: string) {
    setBusy(id);
    setError(null);
    setNotice(null);
    let ok = false;
    try {
      await fn();
      ok = true;
    } catch (e) {
      setError((e as Error).message);
    }
    await reload();
    setBusy(null);
    if (ok) setNotice(done);
  }

  const canEdit = access === "ok";
  const custom = status?.mode === "custom";

  return (
    <main className="mx-auto w-full min-w-0 max-w-[1100px] space-y-5 px-4 py-6 text-[#e5e7eb] sm:px-6">
      <header>
        <h1 className="m-0 text-2xl font-semibold">Data</h1>
        <p className="mt-1 max-w-2xl text-sm text-[#9ca3af]">
          NeuraFlow sits on top of your structured data. Point it at files, Snowflake, Databricks or an SFTP drop folder, confirm how the columns match, and everything (cash flow, credit scores, models) runs on it.
        </p>
      </header>

      {error && <p role="alert" className="rounded-xl border border-[#7f1d1d] bg-[#2a0f12] px-4 py-3 text-sm text-[#fca5a5]">{error}</p>}
      {notice && <p role="status" className="rounded-xl border border-[#065f46] bg-[#052e22] px-4 py-3 text-sm text-[#6ee7b7]">{notice}</p>}
      {!status && !error && <p role="status" className="text-sm text-[#9ca3af]">Loading…</p>}

      {status && (
        <>
          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <Stat label="Using" value={custom ? "Your data" : "Sample data"} tone={custom ? "good" : "warn"} sub={custom ? "Sources you connected" : "Bundled demo data"} />
            <Stat label="Datasets connected" value={`${status.datasets.filter((d) => d.configured).length} of ${status.datasets.length}`} />
            <Stat label="Scheduled refreshes" value={String(status.datasets.filter((d) => d.schedule && d.schedule.mode !== "off").length)} />
            <Stat label="Auto-load from SFTP" value={status.ghost.enabled ? "On" : "Off"} sub={status.ghost.enabled ? scheduleText(status.ghost.schedule ?? undefined) : "Set SFTP_* settings on the server"} />
          </div>

          {!custom && (
            <p role="status" className="rounded-xl border border-[#78350f] bg-[#2b1d07] px-4 py-3 text-sm text-[#fde68a]">
              Everything you see is built-in sample data. Connect your invoices below to replace it. Once any dataset is connected, a dataset with no source is left empty, never filled with sample data.
            </p>
          )}
          {status.warnings.map((w) => (
            <p key={w} role="status" className="rounded-xl border border-[#78350f] bg-[#2b1d07] px-4 py-3 text-sm text-[#fde68a]">{w}</p>
          ))}
          {status.storage.note && <p className="m-0 text-xs text-[#6b7280]">{status.storage.note}</p>}

          {access === "disabled" && (
            <p role="status" className="rounded-xl border border-[#374151] bg-[#111216] px-4 py-3 text-sm text-[#d1d5db]">
              Changing data is turned off on this server. Set <code>ADMIN_TOKEN</code> to turn it on. Until then this page is read-only.
            </p>
          )}
          {access === "needs-token" && (
            <Card title="Enter the admin token">
              <p className="mt-0 text-sm text-[#9ca3af]">Changing data needs the admin token set on the server. It is kept only for this browser session.</p>
              <form className="flex max-w-md gap-2" onSubmit={(e) => { e.preventDefault(); submitToken(); }}>
                <input type="password" aria-label="Admin token" autoComplete="off" className={inputClass} value={tokenText} onChange={(e) => setTokenText(e.target.value)} />
                <button type="submit" disabled={!tokenText.trim()} className="rounded-lg bg-[#2563eb] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-50">Unlock</button>
              </form>
              {tokenError && <p role="alert" className="mb-0 mt-2 text-sm text-[#fca5a5]">{tokenError}</p>}
            </Card>
          )}

          {wizard && (
            <Wizard
              key={wizard.key}
              dataset={wizard}
              connections={conns}
              canSchedule={canEdit}
              onClose={() => setWizard(null)}
              onSaved={async () => {
                const label = wizard.label;
                setWizard(null);
                await reload();
                setNotice(`${label} loaded. The whole app now uses it.`);
              }}
            />
          )}

          <Card title="Datasets" right={canEdit && custom ? <GhostButton danger onClick={() => window.confirm("Remove all connected data and go back to the sample data?") && act("all", resetAll, "Back on sample data.")}>Back to sample data</GhostButton> : undefined}>
            <ul className="m-0 list-none space-y-3 p-0">
              {status.datasets.map((d) => (
                <li key={d.key} className="rounded-xl border border-[#1f2937] p-4" data-testid={`dataset-${d.key}`}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <h3 className="m-0 text-sm font-semibold">{d.label}</h3>
                        {d.configured ? <Badge tone={d.last_run?.ok === false ? "bad" : "good"}>{d.last_run?.ok === false ? "Last refresh failed" : "Connected"}</Badge> : <Badge tone={custom ? "warn" : "neutral"}>{custom ? "Empty" : "Sample data"}</Badge>}
                      </div>
                      <p className="m-0 mt-1 text-xs text-[#6b7280]">{d.description}</p>
                      {d.configured && (
                        <p className="m-0 mt-2 text-sm text-[#d1d5db]">
                          {d.source} · {(d.rows ?? 0).toLocaleString()} rows
                          {d.stats?.date_range ? ` · ${d.stats.date_range[0]} to ${d.stats.date_range[1]}` : ""}
                        </p>
                      )}
                      {d.configured && (
                        <p className="m-0 mt-1 text-xs text-[#9ca3af]">
                          {d.source_kind === "connection" ? scheduleText(d.schedule) : "Uploaded file"}
                          {d.last_run ? ` · last ${d.last_run.ok ? "loaded" : "attempt"} ${when(d.last_run.at)}` : ""}
                          {d.next_run && d.schedule?.mode !== "off" ? ` · next ${when(d.next_run)}` : ""}
                        </p>
                      )}
                      {d.last_run && !d.last_run.ok && <p role="alert" className="m-0 mt-1 text-xs text-[#fca5a5]">{d.last_run.message} The previous data is still in use.</p>}
                      {d.ghost && (
                        <p className="m-0 mt-1 text-xs text-[#9ca3af]">
                          SFTP auto-load looks for <code>{d.ghost.pattern}</code>
                          {d.ghost.state && !d.ghost.state.ok && !d.configured && <span className="text-[#fde68a]"> · {d.ghost.state.message}</span>}
                        </p>
                      )}
                    </div>
                    {canEdit && (
                      <div className="flex flex-wrap gap-2">
                        <GhostButton onClick={() => setWizard(d)}>{d.configured ? "Change" : "Connect"}</GhostButton>
                        {d.configured && d.source_kind === "connection" && (
                          <GhostButton disabled={busy === d.key} onClick={() => act(d.key, () => refreshDataset(d.key).then((r) => { if (!r.ok) throw new Error(r.message); }), `${d.label} refreshed.`)}>{busy === d.key ? "Refreshing…" : "Refresh now"}</GhostButton>
                        )}
                        {d.configured && <GhostButton danger onClick={() => window.confirm(`Disconnect ${d.label}?`) && act(d.key, () => resetDataset(d.key), `${d.label} disconnected.`)}>Disconnect</GhostButton>}
                      </div>
                    )}
                  </div>
                </li>
              ))}
            </ul>
            {canEdit && status.ghost.enabled && (
              <div className="mt-3">
                <GhostButton disabled={busy === "ghost"} onClick={() => act("ghost", ghostScan, "Checked the SFTP folder.")}>{busy === "ghost" ? "Checking…" : "Check SFTP folder now"}</GhostButton>
              </div>
            )}
          </Card>

          {access !== "needs-token" && <ConnectionsCard connections={conns} encryptionReady={encryption} canEdit={canEdit} onChanged={reload} />}
        </>
      )}
    </main>
  );
}
