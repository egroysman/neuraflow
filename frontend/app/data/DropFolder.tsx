"use client";

import { useState } from "react";
import { Card, GhostButton, inputClass } from "../cashflow/ui";
import { setGhost } from "./api";
import type { Connection, DataStatus } from "./types";

const DATASETS: [string, string][] = [
  ["invoices", "Customer invoices"],
  ["bills", "Vendor bills"],
  ["gl_accounts", "Chart of accounts"],
  ["gl_journal", "Journal lines"],
  ["payroll", "Payroll"],
];

function toSchedule(s: DataStatus["ghost"]["schedule"]): string {
  if (!s || s.mode === "off") return "daily@06:00";
  if (s.mode === "interval") return `every ${s.every_minutes} min`;
  return `daily@${s.at}`;
}

export default function DropFolder({ status, connections, onSaved, onError }: { status: DataStatus; connections: Connection[]; onSaved: (m: string) => void; onError: (m: string | null) => void }) {
  const sftp = connections.filter((c) => c.type === "sftp" && !c.env);
  const g = status.ghost;
  const [conn, setConn] = useState(g.connection_id && g.source === "workspace" ? g.connection_id : sftp[0]?.id || "");
  const [pats, setPats] = useState<Record<string, string>>(g.patterns ?? {});
  const [sched, setSched] = useState(toSchedule(g.schedule));
  const [busy, setBusy] = useState(false);

  async function save(off = false) {
    onError(null);
    setBusy(true);
    try {
      await setGhost(off ? null : conn, off ? {} : pats, sched);
      if (off) setPats({});
      onSaved(off ? "Auto-load turned off." : "Auto-load saved. New files are picked up on the schedule.");
    } catch (e) {
      onError((e as Error).message);
    }
    setBusy(false);
  }

  return (
    <Card title="Auto-load from an SFTP folder">
      <p className="mt-0 text-sm text-[#9ca3af]">
        NeuraFlow can watch a folder on your SFTP server and load the newest file that matches each pattern, on a schedule. Add the SFTP connection above first, then say which files to look for (for example <code>invoices_*.csv</code>). Files are matched to fields automatically; anything unclear is left for you to review here.
      </p>
      {sftp.length === 0 ? (
        <p className="m-0 text-sm text-[#d1d5db]">No SFTP connection yet. Add one in Connections above.</p>
      ) : (
        <form className="space-y-3" onSubmit={(e) => { e.preventDefault(); save(); }}>
          <label className="block text-sm">SFTP connection
            <select className={`${inputClass} mt-1 max-w-sm`} value={conn} onChange={(e) => setConn(e.target.value)}>
              {sftp.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
            </select>
          </label>
          <div className="grid gap-2 sm:grid-cols-2">
            {DATASETS.map(([k, label]) => (
              <label key={k} className="text-sm">{label}
                <input className={`${inputClass} mt-1`} placeholder="file name pattern, e.g. invoices_*.csv" value={pats[k] ?? ""} onChange={(e) => setPats({ ...pats, [k]: e.target.value })} />
              </label>
            ))}
          </div>
          <label className="block text-sm">How often
            <select className={`${inputClass} mt-1 max-w-sm`} value={sched} onChange={(e) => setSched(e.target.value)}>
              <option value="daily@06:00">Daily at 06:00</option>
              <option value="daily@18:00">Daily at 18:00</option>
              <option value="every 60 min">Every hour</option>
              <option value="every 15 min">Every 15 minutes</option>
              {!["daily@06:00", "daily@18:00", "every 60 min", "every 15 min"].includes(sched) && <option value={sched}>{sched}</option>}
            </select>
          </label>
          <div className="flex flex-wrap gap-2">
            <button type="submit" disabled={busy || !conn || !Object.values(pats).some((v) => v.trim())} className="rounded-lg bg-[#2563eb] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-50">Save auto-load</button>
            {g.enabled && g.source === "workspace" && <GhostButton danger disabled={busy} onClick={() => save(true)}>Turn off</GhostButton>}
          </div>
        </form>
      )}
    </Card>
  );
}
