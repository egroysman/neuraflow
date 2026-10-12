"use client";

import { useState } from "react";
import { Badge, Card, Field, GhostButton, inputClass } from "../cashflow/ui";
import SetupGuide from "./SetupGuide";
import { createConnection, deleteConnection, observeHostKey, testConnection, updateConnection } from "./api";
import type { ConnType, Connection } from "./types";

type FieldDef = { key: string; label: string; secret?: boolean; multiline?: boolean; hint?: string; placeholder?: string };

const FIELDS: Record<ConnType, FieldDef[]> = {
  snowflake: [
    { key: "account", label: "Account", placeholder: "xy12345.us-east-1", hint: "Your account identifier, without https:// or .snowflakecomputing.com" },
    { key: "user", label: "User" },
    { key: "password", label: "Password", secret: true },
    { key: "private_key", label: "Private key (instead of a password)", secret: true, multiline: true, hint: "PEM text, for key-pair sign-in." },
    { key: "warehouse", label: "Warehouse" },
    { key: "database", label: "Database" },
    { key: "schema", label: "Schema (optional)" },
    { key: "role", label: "Role", hint: "Use a role that can only read the tables you need." },
  ],
  databricks: [
    { key: "server_hostname", label: "Server hostname", placeholder: "adb-123456.7.azuredatabricks.net" },
    { key: "http_path", label: "HTTP path", placeholder: "/sql/1.0/warehouses/abc123" },
    { key: "access_token", label: "Access token", secret: true, hint: "A personal access token or service principal token with read access only." },
    { key: "catalog", label: "Catalog (optional)" },
    { key: "schema", label: "Schema (optional)" },
  ],
  sftp: [
    { key: "host", label: "Host" },
    { key: "port", label: "Port", placeholder: "22" },
    { key: "username", label: "Username" },
    { key: "password", label: "Password", secret: true },
    { key: "private_key", label: "Private key (instead of a password)", secret: true, multiline: true },
    { key: "directory", label: "Folder", placeholder: "/outbound", hint: "Where the files are dropped." },
    { key: "host_key_sha256", label: "Server fingerprint", hint: "Confirms you are talking to your server. Use “Look up fingerprint”, then check it with whoever runs the server." },
  ],
};
const TYPE_LABEL: Record<ConnType, string> = { snowflake: "Snowflake", databricks: "Databricks", sftp: "SFTP" };

function ConnectionForm({ initial, onDone, onCancel, encryptionReady }: { initial: Connection | null; onDone: (id: string, text: string, warn: boolean) => void; onCancel: (saved: boolean) => void; encryptionReady: boolean }) {
  const [type, setType] = useState<ConnType>(initial?.type ?? "snowflake");
  const [name, setName] = useState(initial?.name ?? "");
  const [vals, setVals] = useState<Record<string, string>>(() => Object.fromEntries(Object.entries(initial?.params ?? {}).map(([k, v]) => [k, String(v)])));
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState<{ ok: boolean; text: string } | null>(null);
  const [savedId, setSavedId] = useState<string | null>(initial?.id ?? null); // once saved, later clicks update it instead of adding another
  const [didSave, setDidSave] = useState(false);
  const [guideOpen, setGuideOpen] = useState(false);
  const set = (k: string, v: string) => setVals((p) => ({ ...p, [k]: v }));

  async function lookup() {
    setBusy(true);
    setMsg(null);
    try {
      const r = await observeHostKey({ host: vals.host, port: vals.port || 22 });
      set("host_key_sha256", r.host_key_sha256);
      setMsg({ ok: true, text: "Fingerprint filled in. Check that it matches what your server administrator gives you before saving." });
    } catch (e) {
      setMsg({ ok: false, text: (e as Error).message });
    } finally {
      setBusy(false);
    }
  }

  async function save() {
    setBusy(true);
    setMsg(null);
    let id = savedId;
    let stored = false; // true once this click has saved, so a later failure is the test, not the save
    try {
      const params: Record<string, unknown> = {};
      for (const f of FIELDS[type]) if (vals[f.key]) params[f.key] = vals[f.key];
      const r = id ? await updateConnection(id, name, type, params) : await createConnection(name, type, params);
      id = r.id;
      stored = true;
      setSavedId(r.id);
      setDidSave(true);
      const t = await testConnection(r.id);
      if (t.needs_host_key) {
        setMsg({ ok: false, text: "Saved, but the server's fingerprint is not confirmed. Use “Look up fingerprint”, check it, then save again." });
        if (t.host_key_sha256) set("host_key_sha256", t.host_key_sha256);
        return;
      }
      if (t.warning) {
        setMsg({ ok: false, text: `${t.message} ${t.warning}` });
        return;
      }
      onDone(r.id, t.message, false);
    } catch (e) {
      const m = (e as Error).message;
      setMsg({ ok: false, text: stored ? `Saved, but the connection test failed. ${m}` : m });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-3 rounded-xl border border-[#374151] bg-[#0b0b0f] p-4" role="group" aria-label={initial ? "Edit connection" : "New connection"}>
      {!encryptionReady && (
        <p role="status" className="rounded-lg border border-[#78350f] bg-[#2b1d07] px-3 py-2 text-xs text-[#fde68a]">
          Saving a connection needs <code>CONNECTION_ENCRYPTION_KEY</code> on the server. Until it is set, use server settings for credentials instead.
        </p>
      )}
      {type !== "sftp" && (
        <div>
          <GhostButton onClick={() => setGuideOpen((o) => !o)}>{guideOpen ? "Hide setup guide" : `Setup guide: create a read-only ${TYPE_LABEL[type]} account`}</GhostButton>
          {guideOpen && (
            <div className="mt-2">
              <SetupGuide key={type} type={type} onApply={(values) => setVals((p) => ({ ...p, ...values }))} />
            </div>
          )}
        </div>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Type">
          <select className={inputClass} value={type} disabled={!!initial} onChange={(e) => setType(e.target.value as ConnType)}>
            {(Object.keys(TYPE_LABEL) as ConnType[]).map((t) => (
              <option key={t} value={t}>{TYPE_LABEL[t]}</option>
            ))}
          </select>
        </Field>
        <Field label="Name">
          <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} placeholder="Finance warehouse" maxLength={80} />
        </Field>
        {FIELDS[type].map((f) => {
          const saved = initial?.secrets_set.includes(f.key);
          return (
            <Field key={f.key} label={f.label} hint={f.hint}>
              {f.multiline ? (
                <textarea className={`${inputClass} min-h-20 font-mono text-xs`} value={vals[f.key] ?? ""} onChange={(e) => set(f.key, e.target.value)} placeholder={saved ? "Saved. Leave blank to keep it." : ""} autoComplete="off" spellCheck={false} />
              ) : (
                <input
                  className={inputClass}
                  type={f.secret ? "password" : "text"}
                  value={vals[f.key] ?? ""}
                  onChange={(e) => set(f.key, e.target.value)}
                  placeholder={saved ? "Saved. Leave blank to keep it." : f.placeholder}
                  autoComplete="off"
                />
              )}
            </Field>
          );
        })}
      </div>
      {type === "sftp" && <GhostButton onClick={lookup} disabled={busy || !vals.host}>Look up fingerprint</GhostButton>}
      {msg && <p role={msg.ok ? "status" : "alert"} className={`m-0 whitespace-pre-line text-xs ${msg.ok ? "text-[#6ee7b7]" : "text-[#fca5a5]"}`}>{msg.text}</p>}
      <div className="flex gap-2">
        <button type="button" onClick={save} disabled={busy || !name.trim() || !encryptionReady} className="rounded-lg bg-[#2563eb] px-3 py-1.5 text-sm font-medium text-white hover:bg-[#1d4ed8] disabled:opacity-50">
          {busy ? "Working…" : "Save and test"}
        </button>
        <GhostButton onClick={() => onCancel(didSave)}>{didSave ? "Close" : "Cancel"}</GhostButton>
      </div>
    </div>
  );
}

export default function ConnectionsCard({ connections, encryptionReady, canEdit, onChanged }: { connections: Connection[]; encryptionReady: boolean; canEdit: boolean; onChanged: () => void }) {
  const [editing, setEditing] = useState<Connection | "new" | null>(null);
  const [results, setResults] = useState<Record<string, { ok: boolean; text: string; fp?: string; warn?: boolean }>>({});
  const [busy, setBusy] = useState<string | null>(null);

  async function test(c: Connection) {
    setBusy(c.id);
    try {
      const r = await testConnection(c.id);
      setResults((p) => ({ ...p, [c.id]: r.needs_host_key ? { ok: false, text: r.message, fp: r.host_key_sha256 } : r.warning ? { ok: true, warn: true, text: `${r.message} ${r.warning}` } : { ok: true, text: r.message } }));
    } catch (e) {
      setResults((p) => ({ ...p, [c.id]: { ok: false, text: (e as Error).message } }));
    } finally {
      setBusy(null);
    }
  }
  async function pin(c: Connection, fp: string) {
    setBusy(c.id);
    try {
      await updateConnection(c.id, c.name, c.type, { ...c.params, host_key_sha256: fp });
      await onChanged();
      setResults((p) => ({ ...p, [c.id]: { ok: true, text: "Fingerprint saved." } }));
    } catch (e) {
      setResults((p) => ({ ...p, [c.id]: { ok: false, text: (e as Error).message } }));
    } finally {
      setBusy(null);
    }
  }
  async function remove(c: Connection) {
    if (!window.confirm(`Delete the connection “${c.name}”? Its saved credentials are removed.`)) return;
    setBusy(c.id);
    try {
      await deleteConnection(c.id);
      onChanged();
    } catch (e) {
      setResults((p) => ({ ...p, [c.id]: { ok: false, text: (e as Error).message } }));
    } finally {
      setBusy(null);
    }
  }

  return (
    <Card title="Connections" right={canEdit && !editing ? <GhostButton onClick={() => setEditing("new")}>Add connection</GhostButton> : undefined}>
      <p className="mt-0 text-xs text-[#6b7280]">
        Passwords, tokens and keys are encrypted on the server and are never shown again. Credentials set as server settings appear here too and can only be changed there. Use a read-only account.
      </p>
      {connections.length === 0 && !editing && <p className="text-sm text-[#9ca3af]">No connections yet. Files can be uploaded without one.</p>}
      <ul className="m-0 list-none space-y-2 p-0">
        {connections.map((c) => (
          <li key={c.id} className="rounded-xl border border-[#1f2937] p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-sm font-medium">{c.name}</span>
                <Badge tone="blue">{TYPE_LABEL[c.type]}</Badge>
                {c.env && <Badge>Server setting</Badge>}
              </div>
              {canEdit && (
                <div className="flex gap-2">
                  <GhostButton onClick={() => test(c)} disabled={busy === c.id}>{busy === c.id ? "Testing…" : "Test"}</GhostButton>
                  {!c.env && <GhostButton onClick={() => setEditing(c)}>Edit</GhostButton>}
                  {!c.env && <GhostButton danger onClick={() => remove(c)}>Delete</GhostButton>}
                </div>
              )}
            </div>
            {results[c.id] && (
              <p role="status" className={`m-0 mt-2 whitespace-pre-line text-xs ${results[c.id].warn ? "text-[#fde68a]" : results[c.id].ok ? "text-[#6ee7b7]" : "text-[#fca5a5]"}`}>
                {results[c.id].text}
                {results[c.id].fp && !c.env && (
                  <>
                    {" "}Fingerprint <code>{results[c.id].fp}</code>. Check it with your server administrator.{" "}
                    <GhostButton onClick={() => pin(c, results[c.id].fp as string)}>Trust and pin</GhostButton>
                  </>
                )}
                {results[c.id].fp && c.env && <> Set <code>SFTP_HOST_KEY_SHA256={results[c.id].fp}</code> on the server.</>}
              </p>
            )}
          </li>
        ))}
      </ul>
      {editing && (
        <div className="mt-3">
          <ConnectionForm
            key={editing === "new" ? "new" : editing.id}
            initial={editing === "new" ? null : editing}
            encryptionReady={encryptionReady}
            onCancel={(saved) => {
              setEditing(null);
              if (saved) onChanged();
            }}
            onDone={(id, text, warn) => {
              setEditing(null);
              setResults((p) => ({ ...p, [id]: { ok: true, warn, text } }));
              onChanged();
            }}
          />
        </div>
      )}
    </Card>
  );
}
