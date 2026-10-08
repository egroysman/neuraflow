import type { Adjustments, Assumptions, Defaults, Forecast, GlBaselines, GlOverview, MacroData, Scenario, TabId, Trends } from "./types";

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

export async function fetchTrends(signal?: AbortSignal): Promise<Trends> {
  const res = await fetch(`${API_BASE}/cashflow/trends`, { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

export async function fetchGl(asOf?: string, signal?: AbortSignal): Promise<GlOverview> {
  const res = await fetch(`${API_BASE}/cashflow/gl${asOf ? `?as_of=${encodeURIComponent(asOf)}` : ""}`, { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

/** Replace the ledger-driven assumptions with the baselines from the general ledger. */
export function applyGlBaselines(a: Assumptions, b: GlBaselines): Assumptions {
  const next = structuredClone(a);
  next.general.starting_cash = Math.round(b.starting_cash);
  next.sales.monthly_revenue = Math.round(b.monthly_revenue);
  next.costs.cogs_pct = Math.round(b.cogs_pct * 10) / 10;
  next.capex.existing_depreciation_monthly = Math.round(b.depreciation_monthly);
  next.capex.opening_ppe_net = Math.round(b.ppe_net);
  next.opex = Object.entries(b.opex_monthly).map(([name, amount]) =>
    name === "Marketing" && b.monthly_revenue
      ? { name, kind: "pct_revenue" as const, amount: Math.round((amount / b.monthly_revenue) * 10000) / 100, growth_pct_monthly: 0, start_month: 0, end_month: null }
      : { name, kind: "fixed" as const, amount: Math.round(amount / 50) * 50, growth_pct_monthly: 0, start_month: 0, end_month: null }
  );
  if (b.loan) {
    const rest = next.loans.slice(1);
    next.loans = [
      { name: next.loans[0]?.name || "Term loan", balance: Math.round(b.loan.balance), annual_rate_pct: Math.round(b.loan.annual_rate_pct * 100) / 100, monthly_payment: Math.round(b.loan.monthly_payment), floating: next.loans[0]?.floating ?? false },
      ...rest,
    ];
  }
  return next;
}

export async function fetchMacro(refresh = false, signal?: AbortSignal): Promise<MacroData> {
  const res = await fetch(`${API_BASE}/cashflow/macro${refresh ? "?refresh=true" : ""}`, { signal });
  if (!res.ok) throw new Error(await parseError(res));
  return res.json();
}

/** Format a metric by its unit: $ (compact), days, % / pts. */
export function fmtUnit(value: number, unit: string): string {
  if (unit === "$") return compact(value);
  if (unit === "days") return `${value.toFixed(0)} d`;
  return `${value.toFixed(1)}%`;
}

export const pct = (v: number, digits = 1) => `${v.toFixed(digits)}%`;

/** "2026-03" -> "Mar 2026". */
export function monthLabel(ym: string): string {
  return parseDate(`${ym}-01`).toLocaleDateString("en-US", { month: "short", year: "numeric" });
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


export type AssistantReply = {
  answer: string;
  suggested_whatifs: Partial<Record<keyof Adjustments, number>>;
  follow_ups: string[];
};

export async function askAssistant(
  body: {
    tab: TabId;
    focus: string | null;
    message: string;
    history: { role: "user" | "assistant"; content: string }[];
    forecast: ForecastBody;
  },
  signal?: AbortSignal
): Promise<AssistantReply> {
  const res = await fetch(`${API_BASE}/cashflow/assistant`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    if (res.status === 503) throw new Error("The assistant isn't set up on the server yet (it needs an OpenAI key).");
    if (res.status === 502) throw new Error("The assistant couldn't answer just now. Try again in a moment.");
    throw new Error(await parseError(res));
  }
  const data = await res.json();
  return {
    answer: String(data.answer ?? ""),
    suggested_whatifs: data.suggested_whatifs ?? {},
    follow_ups: Array.isArray(data.follow_ups) ? data.follow_ups.filter((x: unknown) => typeof x === "string") : [],
  };
}
