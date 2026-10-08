"use client";

import { Fragment } from "react";
import { cell, money, shortDate, signed } from "./lib";
import { COLORS, Card, GhostButton } from "./ui";
import type {
  Adjustments,
  AgingRow,
  Category,
  CustomerRow,
  Defaults,
  Forecast,
  Kpis,
  Period,
  Scenario,
  TabId,
  WhatIfGroup,
} from "./types";
import { NO_ADJUSTMENTS } from "./types";

/* ------------------------------------------------------------------ KPIs */

function Kpi({
  label,
  value,
  sub,
  tone = "default",
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "default" | "good" | "warn" | "bad";
}) {
  const color = { default: COLORS.text, good: COLORS.green, warn: COLORS.amber, bad: COLORS.red }[tone];
  return (
    <div className="rounded-xl border border-[#1f2937] bg-[#111216] p-3.5">
      <div className="text-xs font-medium text-[#9ca3af]">{label}</div>
      <div className="mt-1 text-xl font-bold tabular-nums sm:text-2xl" style={{ color }}>
        {value}
      </div>
      {sub && <div className="mt-1 text-xs leading-snug text-[#6b7280]">{sub}</div>}
    </div>
  );
}

export function KpiCards({
  kpis,
  minCash,
  arExpected,
  arOpen,
  windowLabel,
}: {
  kpis: Kpis;
  minCash: number;
  arExpected: number;
  arOpen: number;
  windowLabel: string;
}) {
  const lowTone = kpis.lowest_balance < 0 ? "bad" : kpis.lowest_balance < minCash ? "warn" : "default";
  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 2xl:grid-cols-6">
      <Kpi
        label={`Ending cash (${windowLabel})`}
        value={money(kpis.ending_cash)}
        sub={`From ${money(kpis.starting_cash)} · ${money(kpis.net_cash_flow)} net`}
        tone={kpis.ending_cash < 0 ? "bad" : kpis.ending_cash < minCash ? "warn" : "default"}
      />
      <Kpi
        label="Lowest balance"
        value={money(kpis.lowest_balance)}
        sub={`On ${shortDate(kpis.lowest_balance_date)}`}
        tone={lowTone}
      />
      <Kpi
        label="Runway"
        value={kpis.runway_months !== null ? `${kpis.runway_months} months` : "Stays positive"}
        sub={
          kpis.first_negative_date
            ? `Cash runs out ${shortDate(kpis.first_negative_date)}`
            : kpis.first_below_min_date
              ? `Dips below minimum ${shortDate(kpis.first_below_min_date)}`
              : `Never below ${money(minCash)} minimum`
        }
        tone={kpis.first_negative_date ? "bad" : kpis.first_below_min_date ? "warn" : "good"}
      />
      <Kpi
        label="Funding gap"
        value={kpis.funding_gap > 0 ? money(kpis.funding_gap) : "None"}
        sub={`Needed to always hold ${money(minCash)}`}
        tone={kpis.funding_gap > 0 ? "bad" : "good"}
      />
      <Kpi
        label="Operating / investing / financing"
        value={money(kpis.net_cash_flow)}
        sub={`${money(kpis.operating_cash_flow)} · ${money(kpis.investing_cash_flow)} · ${money(kpis.financing_cash_flow)}`}
        tone={kpis.net_cash_flow < 0 ? "warn" : "default"}
      />
      <Kpi
        label="Receivables expected"
        value={money(arExpected)}
        sub={`Of ${money(arOpen)} open today, after collectability haircuts`}
      />
    </div>
  );
}

/* ------------------------------------------------------- Statement table */

const SECTION_TITLES = {
  operating: "Operating activities",
  investing: "Investing activities",
  financing: "Financing activities",
} as const;

export function StatementTable({
  periods,
  categories,
  minCash,
}: {
  periods: Period[];
  categories: Category[];
  minCash: number;
}) {
  const sections = ["operating", "investing", "financing"] as const;
  const numCell = "px-3 py-1.5 text-right tabular-nums whitespace-nowrap";
  const colour = (n: number) => (n < 0 ? "text-[#f87171]" : "text-[#e5e7eb]");
  const stickyBase = "sticky left-0 z-[1] px-3 py-1.5 text-left whitespace-nowrap";

  return (
    <div className="overflow-x-auto rounded-lg border border-[#1f2937]">
      <table className="w-full border-collapse text-sm">
        <caption className="sr-only">Cash flow statement by period, in US dollars</caption>
        <thead>
          <tr className="bg-[#0b0b0f] text-xs text-[#9ca3af]">
            <th scope="col" className={`${stickyBase} bg-[#0b0b0f] font-medium`}>
              USD
            </th>
            {periods.map((p) => (
              <th key={p.index} scope="col" className="px-3 py-2 text-right font-medium whitespace-nowrap">
                <div>{p.label}</div>
                <div className="text-[10px] font-normal text-[#6b7280]">
                  {shortDate(p.start).replace(/, \d{4}$/, "")}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sections.map((section) => (
            <Fragment key={section}>
              <tr className="bg-[#171a21]">
                <th scope="rowgroup" colSpan={periods.length + 1} className="sticky left-0 px-3 py-1.5 text-left text-xs font-semibold uppercase tracking-wide text-[#9ca3af]">
                  {SECTION_TITLES[section]}
                </th>
              </tr>
              {categories
                .filter((c) => c.section === section)
                .map((c) => (
                  <tr key={c.key} className="border-t border-[#1a1d24]">
                    <th scope="row" className={`${stickyBase} bg-[#111216] font-normal text-[#d1d5db]`}>
                      {c.label}
                    </th>
                    {periods.map((p) => (
                      <td key={p.index} className={`${numCell} ${colour(p.categories[c.key])}`}>
                        {cell(p.categories[c.key])}
                      </td>
                    ))}
                  </tr>
                ))}
              <tr className="border-t border-[#374151] font-semibold">
                <th scope="row" className={`${stickyBase} bg-[#111216]`}>
                  Net {section} cash flow
                </th>
                {periods.map((p) => (
                  <td key={p.index} className={`${numCell} ${colour(p[section])}`}>
                    {cell(p[section])}
                  </td>
                ))}
              </tr>
            </Fragment>
          ))}
          <tr className="border-t-2 border-[#374151] bg-[#101a2e] font-bold">
            <th scope="row" className={`${stickyBase} bg-[#101a2e]`}>
              Net cash flow
            </th>
            {periods.map((p) => (
              <td key={p.index} className={`${numCell} ${colour(p.net)}`}>
                {cell(p.net)}
              </td>
            ))}
          </tr>
          <tr className="border-t border-[#1a1d24] text-[#9ca3af]">
            <th scope="row" className={`${stickyBase} bg-[#111216] font-normal`}>
              Beginning cash
            </th>
            {periods.map((p) => (
              <td key={p.index} className={numCell}>
                {cell(p.begin_cash)}
              </td>
            ))}
          </tr>
          <tr className="border-t border-[#374151] font-bold">
            <th scope="row" className={`${stickyBase} bg-[#111216]`}>
              Ending cash
              <span className="ml-2 text-[10px] font-normal text-[#6b7280]">min {money(minCash)}</span>
            </th>
            {periods.map((p) => (
              <td
                key={p.index}
                className={`${numCell} ${p.end_cash < 0 ? "bg-[#3b1219] text-[#fecaca]" : p.below_min ? "bg-[#3a2a0b] text-[#fde68a]" : "text-[#e5e7eb]"}`}
                title={p.below_min ? "Below your minimum cash target" : undefined}
              >
                {cell(p.end_cash)}
              </td>
            ))}
          </tr>
        </tbody>
      </table>
    </div>
  );
}

/* ----------------------------------------------------- Scenario + what-if */

type Slider = {
  key: keyof Adjustments;
  label: string;
  unit: string;
  min: number;
  max: number;
  step: number;
  digits: number;
  hint: string;
};

const SLIDER_LIST: Slider[] = [
  { key: "collection_delay_days", label: "Customers pay slower (+) or faster (−)", unit: "days", min: -30, max: 60, step: 1, digits: 0, hint: "Shifts every receivable and new-sale collection" },
  { key: "past_due_delay_days", label: "Late invoices pay even later", unit: "days", min: 0, max: 90, step: 1, digits: 0, hint: "Extra delay on invoices already past due" },
  { key: "top_customer_delay_days", label: "Largest customer pays later", unit: "days", min: 0, max: 90, step: 1, digits: 0, hint: "Delays only the customer who owes you the most" },
  { key: "collectability_change_pts", label: "Collectability of open invoices", unit: "pts", min: -30, max: 10, step: 1, digits: 0, hint: "Added to every aging bucket's collect %" },
  { key: "extra_bad_debt_pct", label: "Extra bad debt", unit: "%", min: 0, max: 20, step: 0.5, digits: 1, hint: "Additional share of receivables never collected" },
  { key: "revenue_change_pct", label: "New sales volume", unit: "%", min: -40, max: 40, step: 1, digits: 0, hint: "Level shift on forecast monthly invoicing" },
  { key: "growth_change_pct_pts", label: "Monthly growth", unit: "pts", min: -3, max: 3, step: 0.1, digits: 1, hint: "Added to the monthly growth assumption" },
  { key: "cogs_change_pct_pts", label: "Cost of sales", unit: "pts", min: -10, max: 10, step: 0.5, digits: 1, hint: "Percentage points of revenue" },
  { key: "opex_change_pct", label: "Operating expenses", unit: "%", min: -30, max: 30, step: 1, digits: 0, hint: "Scales every opex line" },
  { key: "dpo_change_days", label: "Pay vendors slower (+) or faster (−)", unit: "days", min: -30, max: 30, step: 1, digits: 0, hint: "Shifts open bills and new vendor payments" },
  { key: "salary_change_pct", label: "Base pay, across the board", unit: "%", min: -20, max: 20, step: 1, digits: 0, hint: "Raises or cuts everyone's base pay" },
  { key: "raise_change_pct_pts", label: "Annual raise", unit: "pts", min: -5, max: 10, step: 0.5, digits: 1, hint: "Added to the raise given in the raise month" },
  { key: "extra_hires", label: "Extra hires", unit: "people", min: 0, max: 20, step: 1, digits: 0, hint: "Start next month at the average base pay" },
  { key: "bonus_change_pct", label: "Bonus pool", unit: "%", min: -100, max: 100, step: 10, digits: 0, hint: "Scales every bonus (−100% = none)" },
  { key: "capex_change_pct", label: "Growth capex", unit: "%", min: -100, max: 100, step: 5, digits: 0, hint: "Defer or accelerate growth capex (it also follows sales changes)" },
  { key: "capex_delay_months", label: "Delay growth capex", unit: "months", min: 0, max: 12, step: 1, digits: 0, hint: "Pushes every growth purchase later" },
  { key: "rate_change_pts", label: "Interest rates", unit: "pts", min: -3, max: 5, step: 0.25, digits: 2, hint: "Floating loans and new financed capex" },
  { key: "tax_rate_change_pts", label: "Income tax rate", unit: "pts", min: -10, max: 15, step: 1, digits: 0, hint: "Added to the tax rate on the General settings" },
];
const SLIDER_BY_KEY = Object.fromEntries(SLIDER_LIST.map((s) => [s.key, s])) as Record<keyof Adjustments, Slider>;

const CORE_KEYS: (keyof Adjustments)[] = [
  "revenue_change_pct", "growth_change_pct_pts", "collection_delay_days", "extra_bad_debt_pct",
  "cogs_change_pct_pts", "opex_change_pct", "dpo_change_days", "capex_change_pct",
];

/** Which sliders each tab shows, which groups' cash impact it reports, and a line about it. */
const TAB_WHATIFS: Record<TabId, { title: string; keys: (keyof Adjustments)[]; groups: WhatIfGroup[]; note: string }> = {
  forecast: { title: "What-ifs: whole forecast", keys: [...CORE_KEYS, "rate_change_pts", "tax_rate_change_pts"], groups: [], note: "Levers for the whole model. Open another tab for more detailed levers." },
  receivables: {
    title: "What-ifs: receivables",
    keys: ["collection_delay_days", "past_due_delay_days", "top_customer_delay_days", "collectability_change_pts", "extra_bad_debt_pct", "revenue_change_pct", "growth_change_pct_pts"],
    groups: ["ar"],
    note: "How fast and how fully customers pay.",
  },
  payroll: { title: "What-ifs: payroll", keys: ["salary_change_pct", "raise_change_pct_pts", "extra_hires", "bonus_change_pct"], groups: ["payroll"], note: "Hiring, pay and bonuses." },
  payables: { title: "What-ifs: payables", keys: ["dpo_change_days", "cogs_change_pct_pts", "opex_change_pct", "revenue_change_pct"], groups: ["payables"], note: "When you pay vendors and what they cost." },
  capex: { title: "What-ifs: capex & financing", keys: ["capex_change_pct", "capex_delay_months", "rate_change_pts", "revenue_change_pct"], groups: ["capex", "financing"], note: "Size, timing and financing cost of purchases." },
  balance: {
    title: "What-ifs: balance sheet drivers",
    keys: ["collection_delay_days", "extra_bad_debt_pct", "dpo_change_days", "capex_change_pct", "rate_change_pts", "tax_rate_change_pts", "opex_change_pct", "revenue_change_pct"],
    groups: [],
    note: "Everything here moves receivables, payables, debt or equity.",
  },
  gl: { title: "What-ifs: actuals vs forecast", keys: [...CORE_KEYS, "rate_change_pts", "tax_rate_change_pts"], groups: [], note: "Compare scenarios with what the ledger shows." },
  trends: { title: "What-ifs: trends", keys: ["revenue_change_pct", "growth_change_pct_pts", "collection_delay_days", "dpo_change_days"], groups: [], note: "Try a trend continuing or reversing." },
};

const SCENARIOS: Scenario[] = ["base", "best", "worst"];

const PRESET_LABELS: Record<keyof Adjustments, string> = {
  collection_delay_days: "collections",
  extra_bad_debt_pct: "bad debt",
  revenue_change_pct: "sales",
  growth_change_pct_pts: "growth",
  cogs_change_pct_pts: "cost of sales",
  opex_change_pct: "opex",
  dpo_change_days: "vendor timing",
  capex_change_pct: "growth capex",
  collectability_change_pts: "collectability",
  past_due_delay_days: "late invoices",
  top_customer_delay_days: "largest customer",
  raise_change_pct_pts: "raises",
  extra_hires: "extra hires",
  bonus_change_pct: "bonuses",
  salary_change_pct: "base pay",
  capex_delay_months: "capex delay",
  rate_change_pts: "rates",
  tax_rate_change_pts: "tax rate",
};

const signedMoney = (v: number) => `${v >= 0 ? "+" : "-"}${money(Math.abs(v))}`;

export function ScenarioPanel({
  scenario,
  onScenario,
  adjustments,
  onAdjustments,
  presets,
  comparison,
  tab = "forecast",
  impact,
}: {
  scenario: Scenario;
  onScenario: (s: Scenario) => void;
  adjustments: Adjustments;
  onAdjustments: (a: Adjustments) => void;
  presets: Defaults["scenarios"];
  comparison: Forecast["comparison"] | undefined;
  tab?: TabId;
  impact?: Forecast["whatif_impact"];
}) {
  const allKeys = Object.keys(NO_ADJUSTMENTS) as (keyof Adjustments)[];
  const dirty = allKeys.some((k) => adjustments[k] !== 0);
  const preset = presets[scenario].adjustments;
  const changes = (Object.keys(preset) as (keyof Adjustments)[]).filter((k) => preset[k] !== 0);
  const cfg = TAB_WHATIFS[tab];
  const shown = cfg.keys.map((k) => SLIDER_BY_KEY[k]);
  const hidden = allKeys.filter((k) => !cfg.keys.includes(k) && adjustments[k] !== 0);
  const activeImpact = impact ? cfg.groups.map((g) => impact[g]).filter((i) => i && i.active) : [];
  const endImpact = activeImpact.reduce((sum, i) => sum + i.ending_cash_impact, 0);
  const lowImpact = activeImpact.reduce((sum, i) => sum + i.lowest_balance_impact, 0);

  return (
    <Card
      title="Scenario & what-if"
      right={
        <GhostButton onClick={() => onAdjustments(NO_ADJUSTMENTS)} disabled={!dirty}>
          Reset sliders
        </GhostButton>
      }
    >
      <div role="radiogroup" aria-label="Scenario" className="grid grid-cols-3 gap-1.5 rounded-xl bg-[#0b0b0f] p-1">
        {SCENARIOS.map((s) => (
          <button
            key={s}
            type="button"
            role="radio"
            aria-checked={scenario === s}
            onClick={() => onScenario(s)}
            className={`rounded-lg px-2 py-2 text-sm font-semibold transition-colors ${
              scenario === s ? "bg-[#1d4ed8] text-white" : "text-[#9ca3af] hover:bg-[#1f2937]"
            }`}
          >
            {presets[s].label.replace(" case", "")}
            {comparison && (
              <span className={`block text-[11px] font-normal tabular-nums ${scenario === s ? "text-[#bfdbfe]" : comparison[s].ending_cash < 0 ? "text-[#f87171]" : "text-[#6b7280]"}`}>
                {money(comparison[s].ending_cash)}
              </span>
            )}
          </button>
        ))}
      </div>
      <p className="mt-2 min-h-[2.2em] text-xs leading-snug text-[#6b7280]">
        {changes.length === 0
          ? "Your assumptions exactly as entered."
          : `Applies on top of your assumptions: ${changes
              .map((k) => `${PRESET_LABELS[k]} ${signed(preset[k], Math.abs(preset[k]) % 1 ? 1 : 0)}`)
              .join(", ")}.`}
      </p>

      <div className="mt-3 border-t border-[#1f2937] pt-3" data-testid="whatif-section" data-tab={tab}>
        <h3 className="m-0 text-sm font-semibold text-[#e5e7eb]">{cfg.title}</h3>
        <p className="mt-0.5 text-[11px] text-[#6b7280]">{cfg.note}</p>

        {activeImpact.length > 0 && (
          <div className="mt-2 rounded-lg border border-[#1e3a8a] bg-[#0c1a33] px-3 py-2 text-xs text-[#bfdbfe]" role="status">
            Your changes here move ending cash by{" "}
            <strong className={endImpact < 0 ? "text-[#fca5a5]" : "text-[#6ee7b7]"}>{signedMoney(endImpact)}</strong> and the lowest balance by{" "}
            <strong className={lowImpact < 0 ? "text-[#fca5a5]" : "text-[#6ee7b7]"}>{signedMoney(lowImpact)}</strong>.
          </div>
        )}

        <div className="mt-3 space-y-3.5">
          {shown.map((s) => {
            const value = adjustments[s.key];
            const id = `slider-${s.key}`;
            return (
              <div key={s.key}>
                <div className="flex items-baseline justify-between gap-2">
                  <label htmlFor={id} className="text-xs font-medium text-[#d1d5db]">
                    {s.label}
                  </label>
                  <span className={`text-xs font-semibold tabular-nums ${value === 0 ? "text-[#6b7280]" : "text-[#60a5fa]"}`}>
                    {signed(value, s.digits)} {s.unit}
                  </span>
                </div>
                <input
                  id={id}
                  type="range"
                  min={s.min}
                  max={s.max}
                  step={s.step}
                  value={value}
                  onChange={(e) => onAdjustments({ ...adjustments, [s.key]: Number(e.target.value) })}
                  className="mt-1 h-1.5 w-full cursor-pointer accent-[#60a5fa]"
                  aria-valuetext={`${signed(value, s.digits)} ${s.unit}`}
                />
                <div className="text-[11px] text-[#6b7280]">{s.hint}</div>
              </div>
            );
          })}
        </div>

        {hidden.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#78350f] bg-[#2b1d07] px-3 py-2 text-xs text-[#fde68a]" role="status">
            <span>
              Also active on other tabs: {hidden.map((k) => `${PRESET_LABELS[k]} ${signed(adjustments[k], SLIDER_BY_KEY[k].digits)} ${SLIDER_BY_KEY[k].unit}`).join(", ")}.
            </span>
            <GhostButton onClick={() => onAdjustments({ ...adjustments, ...Object.fromEntries(hidden.map((k) => [k, 0])) })}>Clear those</GhostButton>
          </div>
        )}
      </div>
    </Card>
  );
}

/* ------------------------------------------------------------ Receivables */

const RISK_STYLE = {
  Low: "bg-[#052e22] text-[#34d399]",
  Medium: "bg-[#3a2a0b] text-[#fbbf24]",
  High: "bg-[#3b1219] text-[#f87171]",
} as const;

const AGING_COLORS = ["#34d399", "#a3e635", "#fbbf24", "#fb923c", "#f87171", "#b91c1c"];

export function ReceivablesPanel({
  ar,
  calibration,
}: {
  ar: Forecast["ar"];
  calibration?: Defaults["data_summary"]["collections_calibration"];
}) {
  const total = ar.aging.reduce((sum: number, a: AgingRow) => sum + a.open_amount, 0) || 1;
  return (
    <Card
      title="Receivables outlook"
      right={
        calibration?.calibrated ? (
          <span className="text-xs text-[#6b7280]">
            Collection rates learned from {calibration.snapshots} historical snapshots
          </span>
        ) : (
          <span className="text-xs text-[#fbbf24]">Generic collection rates (not enough history to calibrate)</span>
        )
      }
    >
      <div className="mb-1 flex h-4 w-full overflow-hidden rounded-full bg-[#0b0b0f]" role="img" aria-label="Open receivables by aging bucket">
        {ar.aging.map((a, i) => (
          <div key={a.bucket} style={{ width: `${(a.open_amount / total) * 100}%`, background: AGING_COLORS[i] }} title={`${a.label}: ${money(a.open_amount)}`} />
        ))}
      </div>
      <div className="mb-4 flex flex-wrap gap-x-4 gap-y-1 text-xs text-[#9ca3af]">
        {ar.aging.map((a, i) => (
          <span key={a.bucket} className="flex items-center gap-1.5">
            <span className="inline-block h-2 w-2 rounded-full" style={{ background: AGING_COLORS[i] }} />
            {a.label} <span className="tabular-nums text-[#d1d5db]">{money(a.open_amount)}</span>
          </span>
        ))}
      </div>
      <div className="overflow-x-auto rounded-lg border border-[#1f2937]">
        <table className="w-full border-collapse text-sm">
          <caption className="sr-only">Largest customers by open receivables</caption>
          <thead>
            <tr className="bg-[#0b0b0f] text-xs text-[#9ca3af]">
              {["Customer", "Open invoices", "Open amount", "Expected in horizon", "Avg days to pay", "Oldest past due", "Risk"].map((h, i) => (
                <th key={h} scope="col" className={`px-3 py-2 font-medium whitespace-nowrap ${i === 0 ? "text-left" : "text-right"}`}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {ar.customers.map((c: CustomerRow) => (
              <tr key={c.customer_id} className="border-t border-[#1a1d24]">
                <th scope="row" className="px-3 py-1.5 text-left font-medium text-[#e5e7eb]">{c.customer_id}</th>
                <td className="px-3 py-1.5 text-right tabular-nums">{c.open_invoices}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{money(c.open_amount)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{money(c.expected_in_horizon)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{c.avg_days_to_pay === null ? "–" : c.avg_days_to_pay.toFixed(0)}</td>
                <td className="px-3 py-1.5 text-right tabular-nums">{c.oldest_days_past_due > 0 ? `${c.oldest_days_past_due} d` : "Not due"}</td>
                <td className="px-3 py-1.5 text-right">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${RISK_STYLE[c.risk]}`}>{c.risk}</span>
                </td>
              </tr>
            ))}
            {ar.customers.length === 0 && (
              <tr>
                <td colSpan={7} className="px-3 py-4 text-center text-[#6b7280]">
                  No open receivables at the forecast start date.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
