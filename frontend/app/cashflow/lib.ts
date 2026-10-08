import type { Adjustments, Assumptions, Defaults, Forecast, Scenario } from "./types";

// Backend base URL. Defaults to the deployed NeuraFlow API (same as the home page); set NEXT_PUBLIC_API_BASE=http://localhost:8000 for local development.
export const API_BASE = (
  process.env.NEXT_PUBLIC_API_BASE || "https://neuraflow-production.up.railway.app"
).replace(/\/$/, "");

const intl = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });

/** Whole-dollar amount with a leading minus, e.g. -$1,234. */
export function money(value: number): string {
  const rounded = Math.round(value);
  return `${rounded < 0 ? "-" : ""}$${intl.format(Math.abs(rounded))}`;
}

/** Table cell: no dollar sign, parentheses for negatives, dash for zero. */
export function cell(value: number): string {
  const rounded = Math.round(value);
  if (rounded === 0) return "–";
  return rounded < 0 ? `(${intl.format(Math.abs(rounded))})` : intl.format(rounded);
}

/** Compact axis label, e.g. $1.2M or -$450k. */
export function compact(value: number): string {
  const abs = Math.abs(value);
  const sign = value < 0 ? "-" : "";
  if (abs >= 1_000_000) return `${sign}$${(abs / 1_000_000).toFixed(abs >= 10_000_000 ? 0 : 1)}M`;
  if (abs >= 1_000) return `${sign}$${Math.round(abs / 1_000)}k`;
  return `${sign}$${Math.round(abs)}`;
}

/** Parse a YYYY-MM-DD string as a local date (avoids timezone day shifts). */
export function parseDate(value: string): Date {
  const [y, m, d] = value.slice(0, 10).split("-").map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
}

export function shortDate(value: string | null): string {
  if (!value) return "–";
  return parseDate(value).toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

export function signed(value: number, digits = 0): string {
  const text = value.toFixed(digits);
  return value > 0 ? `+${text}` : text;
}

async function parseError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (Array.isArray(body?.detail)) {
      return body.detail
        .map((d: { loc?: (string | number)[]; msg?: string }) =>
          `${(d.loc || []).filter((p) => p !== "body").join(" › ")}: ${d.msg}`
        )
        .join("; ");
    }
    if (typeof body?.detail === "string") return body.detail;
  } catch {
    /* fall through */
  }
  return `Request failed (${res.status})`;
}

export async function fetchDefaults(signal?: AbortSignal): Promise<Defaults> {
  const res = await fetch(`${API_BASE}/cashflow/defaults`, { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export type ForecastBody = {
  assumptions: Assumptions;
  scenario: Scenario;
  adjustments: Adjustments;
};

export async function fetchForecast(
  body: ForecastBody,
  signal?: AbortSignal
): Promise<Forecast> {
  const res = await fetch(`${API_BASE}/cashflow/forecast`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function downloadExport(
  body: ForecastBody,
  format: "xlsx" | "csv"
): Promise<void> {
  const res = await fetch(`${API_BASE}/cashflow/export?format=${format}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error(await parseError(res));
  const blob = await res.blob();
  const disposition = res.headers.get("Content-Disposition") || "";
  const match = /filename="?([^";]+)"?/.exec(disposition);
  const name = match?.[1] || `neuraflow_cashflow.${format}`;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
