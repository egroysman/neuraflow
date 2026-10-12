"use client";

import { useRef, useState } from "react";
import { Badge, Card, Field, GhostButton, inputClass } from "../cashflow/ui";
import { analyze, listObjects, saveDataset, uploadFile } from "./api";
import type { Analysis, Connection, DatasetKey, DatasetStatus, Issue, Schedule, Source, SourceObject } from "./types";

const BASE_LINES = ["cash", "ar", "ap", "ppe", "debt", "equity", "revenue", "cogs", "payroll", "depreciation", "interest", "other"];
const LEVEL: Record<Issue["level"], { cls: string; label: string }> = {
  error: { cls: "border-[#7f1d1d] bg-[#2a0f12] text-[#fca5a5]", label: "Must fix" },
  warning: { cls: "border-[#78350f] bg-[#2b1d07] text-[#fde68a]", label: "Check" },
  info: { cls: "border-[#1e3a8a] bg-[#0c1a33] text-[#bfdbfe]", label: "Note" },
};

function cellText(v: unknown): string {
  return v === null || v === undefined ? "" : String(v);
}

function Preview({ rows, caption }: { rows: Record<string, unknown>[]; caption: string }) {
  if (!rows.length) return null;
  const cols = Object.keys(rows[0]);
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr className="border-b border-[#1f2937] text-left text-[#9ca3af]">
            {cols.map((c) => (
              <th key={c} scope="col" className="whitespace-nowrap px-2 py-1.5 font-medium">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={i} className="border-b border-[#1f2937]/60">
              {cols.map((c) => (
                <td key={c} className="max-w-[16rem] truncate whitespace-nowrap px-2 py-1.5 text-[#d1d5db]">{cellText(r[c])}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default function Wizard({ dataset, connections, canSchedule, onClose, onSaved }: { dataset: DatasetStatus; connections: Connection[]; canSchedule: boolean; onClose: () => void; onSaved: () => void }) {
  const key = dataset.key as DatasetKey;
  const [kind, setKind] = useState<"upload" | "connection">("upload");
  const [uploadId, setUploadId] = useState<string>("");
  const [fileName, setFileName] = useState("");
  const [connId, setConnId] = useState(connections[0]?.id ?? "");
  const [objects, setObjects] = useState<SourceObject[]>([]);
  const [object, setObject] = useState("");
  const [customSql, setCustomSql] = useState(false);
  const [headerRow, setHeaderRow] = useState("");
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [mapping, setMapping] = useState<Record<string, string | null>>({});
  const [options, setOptions] = useState<{ date_order?: string; account_overrides?: Record<string, string> }>({});
  const [schedule, setSchedule] = useState<Schedule>({ mode: "off" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const seq = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const conn = connections.find((c) => c.id === connId);
  const isSftp = conn?.type === "sftp";
  const source = (): Source => {
    const hr = headerRow ? { header_row: Number(headerRow) } : {};
    if (kind === "upload") return { kind, upload_id: uploadId, object: object || undefined, ...hr };
    return { kind, connection_id: connId, object: customSql ? `sql:${object}` : object, ...hr };
  };

  async function onFile(f: File | undefined) {
    if (!f) return;
    setBusy(true);
    setError(null);
    setAnalysis(null);
    try {
      const r = await uploadFile(f);
      setUploadId(r.upload.id);
      setFileName(r.upload.filename);
      setObjects(r.objects);
      setObject(r.objects[0]?.name ?? "");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function loadObjects(id: string) {
    setConnId(id);
    setObjects([]);
    setObject("");
    setAnalysis(null);
    if (!id) return;
    setBusy(true);
    setError(null);
    try {
      const r = await listObjects({ kind: "connection", connection_id: id });
      setObjects(r.objects);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  async function run(nextMapping?: Record<string, string | null>, nextOptions?: typeof options) {
    const mine = ++seq.current;
    setBusy(true);
    setError(null);
    try {
      const a = await analyze(key, source(), nextMapping, nextOptions ?? options);
      if (mine !== seq.current) return;
      setAnalysis(a);
      if (!nextMapping) setMapping(a.mapping);
    } catch (e) {
      if (mine === seq.current) setError((e as Error).message);
    } finally {
      if (mine === seq.current) setBusy(false);
    }
  }

  function change(next: Record<string, string | null>, nextOptions = options) {
    setMapping(next);
    setOptions(nextOptions);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => run(next, nextOptions), 350);
  }

  async function save() {
    setBusy(true);
    setError(null);
    try {
      await saveDataset(key, source(), mapping, options, kind === "connection" ? schedule : { mode: "off" });
      onSaved();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const ready = kind === "upload" ? !!uploadId && (!objects.length || !!object) : !!connId && !!object.trim();
  const errors = analysis?.validation.issues.filter((i) => i.level === "error") ?? [];

  return (
    <Card title={`Set up: ${dataset.label}`} right={<GhostButton onClick={onClose}>Close</GhostButton>}>
      <p className="mt-0 text-sm text-[#9ca3af]">{dataset.description}</p>
      {error && <p role="alert" className="rounded-lg border border-[#7f1d1d] bg-[#2a0f12] px-3 py-2 text-sm text-[#fca5a5]">{error}</p>}

      <section aria-label="Choose the source" className="space-y-3">
        <h3 className="m-0 text-sm font-semibold">1. Where is the data?</h3>
        <div role="radiogroup" aria-label="Source type" className="flex flex-wrap gap-2">
          {([["upload", "Upload a file (CSV or Excel)"], ["connection", "A connection (Snowflake, Databricks, SFTP)"]] as const).map(([k, label]) => (
            <button
              key={k}
              type="button"
              role="radio"
              aria-checked={kind === k}
              onClick={() => {
                setKind(k);
                setAnalysis(null);
                setObjects([]);
                setObject("");
                if (k === "connection" && connId) loadObjects(connId);
              }}
              className={`rounded-lg border px-3 py-1.5 text-sm ${kind === k ? "border-[#3b82f6] bg-[#0c1a33] text-white" : "border-[#374151] text-[#d1d5db] hover:bg-[#1f2937]"}`}
            >
              {label}
            </button>
          ))}
        </div>

        {kind === "upload" ? (
          <div className="space-y-3">
            <Field label="File" hint="Excel (.xlsx) or CSV. Title rows above the headers are skipped.">
              <input type="file" accept=".csv,.tsv,.txt,.xlsx,.xlsm,.gz" aria-label="File to upload" className="block text-sm text-[#d1d5db]" onChange={(e) => onFile(e.target.files?.[0])} />
            </Field>
            {fileName && <p className="m-0 text-xs text-[#6ee7b7]">Uploaded {fileName}.</p>}
            {objects.length > 1 && (
              <Field label="Sheet">
                <select className={inputClass} value={object} onChange={(e) => { setObject(e.target.value); setAnalysis(null); }}>
                  {objects.map((o) => (
                    <option key={o.name} value={o.name}>{o.name}{o.detail ? ` (${o.detail})` : ""}</option>
                  ))}
                </select>
              </Field>
            )}
          </div>
        ) : connections.length === 0 ? (
          <p className="text-sm text-[#fde68a]">Add a connection below first.</p>
        ) : (
          <div className="space-y-3">
            <Field label="Connection">
              <select className={inputClass} value={connId} onChange={(e) => loadObjects(e.target.value)}>
                {connections.map((c) => (
                  <option key={c.id} value={c.id}>{c.name}</option>
                ))}
              </select>
            </Field>
            {isSftp ? (
              <Field label="File name or pattern" hint="A wildcard such as invoices*.csv always picks the newest matching file.">
                <input className={inputClass} value={object} onChange={(e) => { setObject(e.target.value); setAnalysis(null); }} placeholder="invoices*.csv" list="sftp-files" />
                <datalist id="sftp-files">
                  {objects.map((o) => (
                    <option key={o.name} value={o.name}>{o.detail}</option>
                  ))}
                </datalist>
              </Field>
            ) : (
              <>
                <label className="flex items-center gap-2 text-xs text-[#9ca3af]">
                  <input type="checkbox" checked={customSql} onChange={(e) => { setCustomSql(e.target.checked); setObject(""); setAnalysis(null); }} /> Use a custom query instead of a table
                </label>
                {customSql ? (
                  <Field label="Query" hint="One read-only SELECT. Join or filter here if your data is spread across tables.">
                    <textarea className={`${inputClass} min-h-24 font-mono text-xs`} value={object} onChange={(e) => { setObject(e.target.value); setAnalysis(null); }} spellCheck={false} placeholder="SELECT * FROM finance.ar_open_items" />
                  </Field>
                ) : (
                  <Field label="Table or view">
                    <select className={inputClass} value={object} onChange={(e) => { setObject(e.target.value); setAnalysis(null); }}>
                      <option value="">Choose…</option>
                      {objects.map((o) => (
                        <option key={o.name} value={o.name}>{o.name}{o.detail ? ` (${o.detail})` : ""}</option>
                      ))}
                    </select>
                  </Field>
                )}
              </>
            )}
          </div>
        )}
        <details className="text-xs text-[#9ca3af]">
          <summary className="cursor-pointer">Headers are not on the first row?</summary>
          <div className="mt-2 max-w-40">
            <Field label="Header row number" hint="Leave blank to detect it.">
              <input className={inputClass} inputMode="numeric" value={headerRow} onChange={(e) => setHeaderRow(e.target.value.replace(/\D/g, ""))} />
            </Field>
          </div>
        </details>
        <button type="button" onClick={() => run()} disabled={!ready || busy} className="rounded-lg bg-[#2563eb] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-50">
          {busy && !analysis ? "Reading…" : "Read the data"}
        </button>
      </section>

      {analysis && (
        <>
          <section aria-label="Match the columns" className="mt-6 space-y-3">
            <h3 className="m-0 text-sm font-semibold">2. Match the columns</h3>
            <p className="m-0 text-xs text-[#6b7280]">
              {analysis.row_count.toLocaleString()} rows read{analysis.truncated ? " (more were left out by the row limit)" : ""}. We matched columns by name and by what is in them. Change anything that looks wrong.
            </p>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">Which column in your data feeds each NeuraFlow field</caption>
                <thead>
                  <tr className="border-b border-[#1f2937] text-left text-xs text-[#9ca3af]">
                    <th scope="col" className="py-2 pr-3 font-medium">NeuraFlow needs</th>
                    <th scope="col" className="py-2 pr-3 font-medium">Your column</th>
                    <th scope="col" className="py-2 font-medium">What is in it</th>
                  </tr>
                </thead>
                <tbody>
                  {analysis.fields.map((f) => {
                    const col = mapping[f.name] ?? "";
                    const sug = analysis.suggestions[f.name];
                    const samples = col && sug?.column === col ? sug.samples : col ? analysis.raw_sample.map((r) => cellText(r[col])).filter(Boolean).slice(0, 3) : [];
                    return (
                      <tr key={f.name} className="border-b border-[#1f2937]/60 align-top">
                        <th scope="row" className="py-2 pr-3 text-left font-normal">
                          <label htmlFor={`map-${f.name}`}>{f.label}{f.required && <span className="text-[#f87171]" aria-label="required"> *</span>}</label>
                          {f.help && <div className="text-[11px] text-[#6b7280]">{f.help}</div>}
                        </th>
                        <td className="py-2 pr-3">
                          <select id={`map-${f.name}`} className={inputClass} value={col} onChange={(e) => change({ ...mapping, [f.name]: e.target.value || null })}>
                            <option value="">Not used</option>
                            {analysis.columns.map((c) => (
                              <option key={c} value={c}>{c}</option>
                            ))}
                          </select>
                          {sug && col === sug.column && <div className="mt-1"><Badge tone={sug.confidence >= 0.85 ? "good" : "warn"}>{sug.confidence >= 0.85 ? "Good match" : "Check this one"}</Badge></div>}
                        </td>
                        <td className="py-2 text-xs text-[#9ca3af]">{samples.join(" · ")}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
            {analysis.at_least_one_of.length > 0 && (
              <p className="m-0 text-xs text-[#6b7280]">Needs at least one of: {analysis.at_least_one_of.map((g) => g.map((n) => analysis.fields.find((f) => f.name === n)?.label).join(" / ")).join("; ")}.</p>
            )}
            <details className="text-xs text-[#9ca3af]" open={!!analysis.report.ambiguous_dates}>
              <summary className="cursor-pointer">Date format</summary>
              <div className="mt-2 max-w-xs">
                <Field label="Dates like 03/04/2026 mean" hint="Only matters when the day and month could be swapped.">
                  <select className={inputClass} value={options.date_order ?? ""} onChange={(e) => change(mapping, { ...options, date_order: e.target.value || undefined })}>
                    <option value="">Detect automatically</option>
                    <option value="MDY">Month first (US): 3 April is 03/04</option>
                    <option value="DMY">Day first: 3 April is 03/04</option>
                  </select>
                </Field>
              </div>
            </details>
            <details className="text-xs text-[#9ca3af]">
              <summary className="cursor-pointer">Your source data (first rows)</summary>
              <div className="mt-2"><Preview rows={analysis.raw_sample} caption="First rows of your data" /></div>
            </details>
          </section>

          <section aria-label="Check the result" className="mt-6 space-y-3">
            <h3 className="m-0 text-sm font-semibold">3. Check the result</h3>
            <div aria-live="polite" className="space-y-2">
              {analysis.validation.issues.length === 0 && <p className="m-0 rounded-lg border border-[#065f46] bg-[#052e22] px-3 py-2 text-sm text-[#6ee7b7]">All checks passed. {analysis.report.rows_out.toLocaleString()} of {analysis.report.rows_in.toLocaleString()} rows will load.</p>}
              {analysis.validation.issues.map((i, n) => (
                <p key={n} className={`m-0 rounded-lg border px-3 py-2 text-sm ${LEVEL[i.level].cls}`}><strong>{LEVEL[i.level].label}:</strong> {i.message}</p>
              ))}
              {analysis.validation.ok && analysis.validation.issues.length > 0 && <p className="m-0 text-xs text-[#9ca3af]">{analysis.report.rows_out.toLocaleString()} of {analysis.report.rows_in.toLocaleString()} rows will load.</p>}
            </div>
            <Preview rows={analysis.mapped_sample} caption="How the first rows will load" />
            {analysis.classified && (
              <details className="text-sm" open={analysis.classified.some((c) => c.inferred)}>
                <summary className="cursor-pointer font-medium">How each account feeds the forecast ({analysis.classified.filter((c) => c.inferred).length} worked out from names)</summary>
                <p className="text-xs text-[#6b7280]">Pick the forecast line for any account we got wrong. For an expense type opex:Name to group it as its own operating cost.</p>
                <datalist id="model-lines">
                  {BASE_LINES.map((l) => (
                    <option key={l} value={l} />
                  ))}
                </datalist>
                <div className="max-h-72 overflow-auto">
                  <table className="w-full text-xs">
                    <caption className="sr-only">Ledger accounts and the forecast line each feeds</caption>
                    <thead>
                      <tr className="border-b border-[#1f2937] text-left text-[#9ca3af]">
                        <th scope="col" className="py-1.5 font-medium">Account</th>
                        <th scope="col" className="py-1.5 font-medium">Type</th>
                        <th scope="col" className="py-1.5 font-medium">Forecast line</th>
                      </tr>
                    </thead>
                    <tbody>
                      {analysis.classified.map((c) => (
                        <tr key={c.AccountID} className="border-b border-[#1f2937]/60">
                          <td className="py-1.5 pr-2">{c.AccountID} · {c.AccountName}</td>
                          <td className="py-1.5 pr-2">{c.AccountType}</td>
                          <td className="py-1.5">
                            <input
                              aria-label={`Forecast line for ${c.AccountName}`}
                              list="model-lines"
                              className={`${inputClass} !py-1`}
                              defaultValue={c.ModelLine}
                              onBlur={(e) => {
                                const v = e.target.value.trim();
                                if (v && v !== c.ModelLine) change(mapping, { ...options, account_overrides: { ...(options.account_overrides ?? {}), [c.AccountID]: v } });
                              }}
                            />
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </details>
            )}
          </section>

          {kind === "connection" && (
            <section aria-label="Keep it up to date" className="mt-6 space-y-3">
              <h3 className="m-0 text-sm font-semibold">4. Keep it up to date</h3>
              {!canSchedule ? (
                <p className="m-0 text-xs text-[#6b7280]">Refreshing on a schedule is available once an admin token is set.</p>
              ) : (
                <div className="grid max-w-xl gap-3 sm:grid-cols-3">
                  <Field label="Refresh">
                    <select className={inputClass} value={schedule.mode} onChange={(e) => setSchedule(e.target.value === "interval" ? { mode: "interval", every_minutes: 60 } : e.target.value === "daily" ? { mode: "daily", at: "06:00", timezone: Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC" } : { mode: "off" })}>
                      <option value="off">Only when I ask</option>
                      <option value="interval">Every few minutes or hours</option>
                      <option value="daily">Once a day</option>
                    </select>
                  </Field>
                  {schedule.mode === "interval" && (
                    <Field label="Every (minutes)" hint="At least 15.">
                      <input className={inputClass} inputMode="numeric" value={schedule.every_minutes ?? ""} onChange={(e) => setSchedule({ mode: "interval", every_minutes: Number(e.target.value.replace(/\D/g, "")) || 0 })} />
                    </Field>
                  )}
                  {schedule.mode === "daily" && (
                    <>
                      <Field label="At">
                        <input type="time" className={inputClass} value={schedule.at ?? "06:00"} onChange={(e) => setSchedule({ ...schedule, at: e.target.value })} />
                      </Field>
                      <Field label="Time zone">
                        <input className={inputClass} value={schedule.timezone ?? ""} onChange={(e) => setSchedule({ ...schedule, timezone: e.target.value })} />
                      </Field>
                    </>
                  )}
                </div>
              )}
              <p className="m-0 text-xs text-[#6b7280]">A refresh with bad or much smaller data never replaces what is already loaded.</p>
            </section>
          )}

          <div className="mt-6 flex flex-wrap items-center gap-3">
            <button type="button" onClick={save} disabled={busy || !analysis.validation.ok} className="rounded-lg bg-[#2563eb] px-4 py-2 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:cursor-not-allowed disabled:opacity-50">
              {busy ? "Working…" : `Load ${analysis.report.rows_out.toLocaleString()} rows`}
            </button>
            {errors.length > 0 && <span className="text-xs text-[#fca5a5]">Fix the items marked “Must fix” first.</span>}
            <GhostButton onClick={onClose}>Cancel</GhostButton>
          </div>
        </>
      )}
    </Card>
  );
}
