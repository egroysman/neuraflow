"use client";

import { useState } from "react";
import { Field, GhostButton, inputClass } from "../cashflow/ui";
import { getSetupGuide } from "./api";
import type { ConnType, SetupGuide as Guide } from "./types";

function CopyBlock({ sql }: { sql: string }) {
  const [copied, setCopied] = useState(false);
  async function copy() {
    try {
      await navigator.clipboard.writeText(sql);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      /* select the text and copy it by hand */
    }
  }
  return (
    <div className="mt-2">
      <pre className="m-0 overflow-x-auto whitespace-pre rounded-lg bg-[#0b0b0f] p-3 text-xs text-[#d1d5db]"><code>{sql}</code></pre>
      <div className="mt-1"><GhostButton onClick={copy}>{copied ? "Copied" : "Copy"}</GhostButton></div>
    </div>
  );
}

/** Walks an administrator through creating a read-only account in their own warehouse. */
export default function SetupGuide({ type, onApply }: { type: Exclude<ConnType, "sftp">; onApply: (values: Record<string, string>) => void }) {
  const [v, setV] = useState<Record<string, string>>({ auth: "key" });
  const [guide, setGuide] = useState<Guide | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [applied, setApplied] = useState(false);
  const set = (k: string, val: string) => setV((p) => ({ ...p, [k]: val }));
  const snow = type === "snowflake";
  const ready = snow ? !!v.database?.trim() : !!v.principal?.trim() && !!v.catalog?.trim();

  async function make() {
    setBusy(true);
    setError(null);
    setApplied(false);
    try {
      setGuide(await getSetupGuide(type, v));
    } catch (e) {
      setGuide(null);
      setError((e as Error).message);
    }
    setBusy(false);
  }

  return (
    <div className="space-y-3 rounded-xl border border-[#1e3a8a] bg-[#0f1a33] p-4" role="group" aria-label="Setup guide">
      <p className="m-0 text-sm text-[#bfdbfe]">
        Give NeuraFlow its own <strong>read-only</strong> account. Answer a few questions and we write the exact steps for your administrator to review and run. NeuraFlow never runs these itself and never gets more than read access.
      </p>
      <div className="grid gap-3 sm:grid-cols-2">
        {snow ? (
          <>
            <Field label="Database to read" hint="Where your invoices, bills and ledger live."><input className={inputClass} value={v.database ?? ""} onChange={(e) => set("database", e.target.value)} placeholder="FINANCE" /></Field>
            <Field label="Schemas" hint="Comma separated. Default PUBLIC."><input className={inputClass} value={v.schemas ?? ""} onChange={(e) => set("schemas", e.target.value)} placeholder="ERP, GL" /></Field>
            <Field label="Role name"><input className={inputClass} value={v.role ?? ""} onChange={(e) => set("role", e.target.value)} placeholder="NEURAFLOW_READER" /></Field>
            <Field label="Warehouse name"><input className={inputClass} value={v.warehouse ?? ""} onChange={(e) => set("warehouse", e.target.value)} placeholder="NEURAFLOW_WH" /></Field>
            <Field label="User name"><input className={inputClass} value={v.user ?? ""} onChange={(e) => set("user", e.target.value)} placeholder="NEURAFLOW_SVC" /></Field>
            <Field label="How it signs in">
              <select className={inputClass} value={v.auth} onChange={(e) => set("auth", e.target.value)}>
                <option value="key">Key pair (recommended)</option>
                <option value="password">Password</option>
              </select>
            </Field>
          </>
        ) : (
          <>
            <Field label="Service principal" hint="Its application ID or name."><input className={inputClass} value={v.principal ?? ""} onChange={(e) => set("principal", e.target.value)} placeholder="neuraflow-reader" /></Field>
            <Field label="Catalog"><input className={inputClass} value={v.catalog ?? ""} onChange={(e) => set("catalog", e.target.value)} placeholder="main" /></Field>
            <Field label="Schemas" hint="Comma separated. Default “default”."><input className={inputClass} value={v.schemas ?? ""} onChange={(e) => set("schemas", e.target.value)} placeholder="finance" /></Field>
          </>
        )}
      </div>
      <button type="button" onClick={make} disabled={!ready || busy} className="rounded-lg bg-[#2563eb] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-50">{busy ? "Working…" : guide ? "Update steps" : "Show the steps"}</button>
      {error && <p role="alert" className="m-0 text-xs text-[#fca5a5]">{error}</p>}
      {guide && (
        <div className="space-y-3" data-testid="setup-steps">
          <ol className="m-0 list-none space-y-3 p-0">
            {guide.steps.map((s, i) => (
              <li key={i} className="rounded-lg border border-[#1f2937] bg-[#111216] p-3">
                <p className="m-0 text-sm font-semibold text-[#e5e7eb]">{i + 1}. {s.title}{s.optional ? <span className="ml-2 text-xs font-normal text-[#9ca3af]">if needed</span> : null}</p>
                <p className="m-0 mt-1 text-xs text-[#9ca3af]">{s.text}</p>
                {s.sql && <CopyBlock sql={s.sql} />}
              </li>
            ))}
          </ol>
          <p className="m-0 text-xs text-[#9ca3af]">These are templates. Have your administrator read them before running; every grant is read-only.</p>
          <div className="flex flex-wrap items-center gap-2">
            <GhostButton onClick={() => { onApply(guide.fill); setApplied(true); }}>Use these names in the form</GhostButton>
            {applied && <span role="status" className="text-xs text-[#6ee7b7]">Filled in. {guide.then}</span>}
          </div>
        </div>
      )}
    </div>
  );
}
