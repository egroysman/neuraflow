// Workspace sign-in: the access key lives in this browser only and is sent with every request.
import { API_BASE } from "./cashflow/lib";

const KEY = "nf_workspace_key";
const CHANGED = "nf-auth-changed";

export type Session = { id: string; name: string; role: "admin" | "viewer"; legacy: boolean; starts_with: "empty" | "sample" };

export function getKey(): string {
  try {
    return sessionStorage.getItem(KEY) || localStorage.getItem(KEY) || "";
  } catch {
    return "";
  }
}

/** Remember the key for this tab only, or on this device until the person signs out. */
export function setKey(key: string, remember = false) {
  try {
    sessionStorage.removeItem(KEY);
    localStorage.removeItem(KEY);
    if (key) (remember ? localStorage : sessionStorage).setItem(KEY, key);
  } catch {
    /* private window: the key is lost on reload and the person signs in again */
  }
  window.dispatchEvent(new Event(CHANGED));
}

export function onAuthChange(fn: () => void): () => void {
  window.addEventListener(CHANGED, fn);
  return () => window.removeEventListener(CHANGED, fn);
}

/** fetch() that signs the request with the workspace key. A rejected key signs the person out. */
export async function authFetch(input: string, init: RequestInit = {}): Promise<Response> {
  const key = getKey();
  const headers = new Headers(init.headers);
  if (key && !headers.has("Authorization")) headers.set("Authorization", `Bearer ${key}`);
  const res = await fetch(input, { ...init, headers });
  if (key && res.status === 401 && getKey() === key) setKey("");
  return res;
}

export async function fetchMode(): Promise<{ mode: "open" | "required"; platform_admin: boolean }> {
  const res = await fetch(`${API_BASE}/auth/mode`);
  if (!res.ok) throw new Error("Could not reach the server.");
  return res.json();
}

/** Check a key. Resolves with the session, or throws with a message the person can act on. */
export async function checkKey(key: string): Promise<Session> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/auth/session`, { headers: key ? { Authorization: `Bearer ${key}` } : {} });
  } catch {
    throw new Error("Could not reach the server. Check your connection and try again.");
  }
  if (!res.ok) {
    let msg = res.status === 429 ? "Too many attempts. Wait a few minutes and try again." : "That key was not recognised.";
    try {
      const j = await res.json();
      if (typeof j?.detail === "string") msg = j.detail;
    } catch {
      /* keep the generic message */
    }
    throw new Error(msg);
  }
  return (await res.json()).workspace;
}

/** Download a file the API returns, sending the key (a plain link cannot). */
export async function downloadFile(url: string, fallbackName: string): Promise<void> {
  const res = await authFetch(url);
  if (!res.ok) throw new Error(`Download failed (${res.status}).`);
  const blob = await res.blob();
  const name = /filename="?([^";]+)"?/.exec(res.headers.get("Content-Disposition") || "")?.[1] || fallbackName;
  const href = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = href;
  a.download = name;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(href);
}
