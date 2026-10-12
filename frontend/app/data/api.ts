import { API_BASE } from "../cashflow/lib";
import { authFetch } from "../auth";
import type { ActivityEvent, Analysis, Connection, ConnType, DataStatus, DatasetKey, LastRun, Schedule, Source, SourceObject } from "./types";

const KEY = "nf_admin_token";

export function getToken(): string {
  try {
    return sessionStorage.getItem(KEY) || "";
  } catch {
    return "";
  }
}
export function setToken(t: string) {
  try {
    if (t) sessionStorage.setItem(KEY, t);
    else sessionStorage.removeItem(KEY);
  } catch {
    /* private window: the token lives only until the page reloads */
  }
}

export class ApiError extends Error {
  status: number;
  code?: string;
  data?: Record<string, unknown>;
  constructor(message: string, status: number, code?: string, data?: Record<string, unknown>) {
    super(message);
    this.status = status;
    this.code = code;
    this.data = data;
  }
}

async function call<T>(method: string, path: string, body?: unknown, form?: FormData): Promise<T> {
  const headers: Record<string, string> = {};
  const t = getToken();
  if (t) headers["X-Admin-Token"] = t;
  if (body !== undefined) headers["Content-Type"] = "application/json";
  let res: Response;
  try {
    res = await authFetch(`${API_BASE}/data${path}`, { method, headers, body: form ?? (body !== undefined ? JSON.stringify(body) : undefined) });
  } catch {
    throw new ApiError("Could not reach the server. Check your connection and try again.", 0);
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status}).`;
    let code: string | undefined;
    let data: Record<string, unknown> | undefined;
    try {
      const j = await res.json();
      if (typeof j?.detail === "string") msg = j.detail;
      else if (j?.detail?.message) {
        msg = j.detail.message;
        code = j.detail.code;
        data = j.detail;
      } else if (Array.isArray(j?.detail)) msg = j.detail.map((d: { msg?: string }) => d.msg).join("; ");
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(msg, res.status, code, data);
  }
  return res.json();
}

export const getStatus = () => call<DataStatus>("GET", "/status");
export const listConnections = () => call<{ connections: Connection[]; encryption_ready: boolean }>("GET", "/connections");
export const createConnection = (name: string, type: ConnType, params: Record<string, unknown>) => call<{ id: string }>("POST", "/connections", { name, type, params });
export const updateConnection = (id: string, name: string, type: ConnType, params: Record<string, unknown>) => call<{ id: string }>("PUT", `/connections/${encodeURIComponent(id)}`, { name, type, params });
export const deleteConnection = (id: string) => call<{ ok: boolean }>("DELETE", `/connections/${encodeURIComponent(id)}`);
export const testConnection = (id: string) => call<{ ok: boolean; message: string; needs_host_key?: boolean; host_key_sha256?: string }>("POST", `/connections/${encodeURIComponent(id)}/test`);
export const observeHostKey = (params: Record<string, unknown>) => call<{ host_key_sha256: string }>("POST", "/connections/host-key", { name: "x", type: "sftp", params });
export function uploadFile(file: File) {
  const f = new FormData();
  f.append("file", file);
  return call<{ upload: { id: string; filename: string; size: number }; objects: SourceObject[] }>("POST", "/upload", undefined, f);
}
export const listObjects = (source: Source) => call<{ objects: SourceObject[] }>("POST", "/objects", source);
export const analyze = (key: DatasetKey, source: Source, mapping?: Record<string, string | null>, options?: Record<string, unknown>) =>
  call<Analysis>("POST", `/${key}/analyze`, { source, mapping, options });
export const saveDataset = (key: DatasetKey, source: Source, mapping: Record<string, string | null>, options: Record<string, unknown>, schedule: Schedule) =>
  call<{ ok: boolean; rows: number }>("PUT", `/${key}`, { source, mapping, options, schedule });
export const refreshDataset = (key: DatasetKey) => call<LastRun>("POST", `/${key}/refresh`);
export const setSchedule = (key: DatasetKey, s: Schedule) => call<Schedule>("PUT", `/${key}/schedule`, s);
export const resetDataset = (key: DatasetKey) => call<{ ok: boolean }>("DELETE", `/${key}`);
export const resetAll = () => call<{ ok: boolean }>("POST", "/reset");
export const ghostScan = () => call<{ state: Record<string, { ok: boolean; message: string }> }>("POST", "/ghost/scan");
export const setGhost = (connection_id: string | null, patterns: Record<string, string>, schedule: string) => call<{ ghost: unknown }>("PUT", "/ghost", { connection_id, patterns, schedule });
export const getActivity = () => call<{ events: ActivityEvent[] }>("GET", "/activity");
