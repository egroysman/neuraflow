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
  /** Show as dollars, e.g. +$5,000 */
  money?: boolean;
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
  { key: "bill_catchup_extra_days", label: "Clear overdue bills slower", unit: "days", min: 0, max: 90, step: 1, digits: 0, hint: "Extra days on bills that are already past due" },
  { key: "top_vendor_delay_days", label: "Pay your largest vendor later", unit: "days", min: 0, max: 90, step: 1, digits: 0, hint: "Delays only the vendor you owe the most" },
  { key: "benefits_change_pct", label: "Benefits cost", unit: "%", min: -30, max: 60, step: 5, digits: 0, hint: "Scales every employee's benefits" },
  { key: "employer_tax_change_pts", label: "Employer payroll taxes", unit: "pts", min: -3, max: 6, step: 0.5, digits: 1, hint: "Added to the employer tax rate" },
  { key: "maintenance_capex_change_pct", label: "Maintenance capex", unit: "%", min: -100, max: 200, step: 10, digits: 0, hint: "Scales recurring and planned maintenance purchases" },
  { key: "down_payment_change_pts", label: "Down payment on financed items", unit: "pts", min: -20, max: 50, step: 5, digits: 0, hint: "More cash up front, smaller loans or leases" },
  { key: "extra_loan_payment", label: "Extra payment on the first loan", unit: "/mo", min: 0, max: 20000, step: 500, digits: 0, hint: "Paid every month on top of the scheduled payment", money: true },
  { key: "equity_injection", label: "Owner cash in (+) or out (−)", unit: "", min: -500000, max: 500000, step: 10000, digits: 0, hint: "One-time, at the start date", money: true },
  { key: "starting_cash_change", label: "Starting cash vs ledger", unit: "", min: -250000, max: 250000, step: 5000, digits: 0, hint: "What if the bank balance is not what the ledger says", money: true },
  { key: "other_monthly_cash", label: "Other cash each month", unit: "/mo", min: -50000, max: 50000, step: 1000, digits: 0, hint: "Items not in any assumption, in (+) or out (−)", money: true },
  { key: "one_time_cash_item", label: "Surprise one-off item", unit: "", min: -250000, max: 250000, step: 5000, digits: 0, hint: "Lands in month 3", money: true },
  { key: "seasonal_swing_pct", label: "Seasonal swing in sales", unit: "%", min: 0, max: 40, step: 5, digits: 0, hint: "Sales peak in December and dip in June" },
  { key: "top_customer_loss_pct", label: "Lose part of the largest customer", unit: "%", min: 0, max: 100, step: 5, digits: 0, hint: "Share of their sales (last 12 months) that goes away" },
  { key: "new_sales_dso_change_days", label: "New sales pay slower (+) or faster (−)", unit: "days", min: -20, max: 60, step: 1, digits: 0, hint: "Affects new invoices only, not today's open ones" },
];
export const SLIDER_BY_KEY = Object.fromEntries(SLIDER_LIST.map((s) => [s.key, s])) as Record<keyof Adjustments, Slider>;

/** Every lever lives on exactly one tab. */
const TAB_WHATIFS: Record<TabId, { title: string; keys: (keyof Adjustments)[]; groups: WhatIfGroup[]; note: string }> = {
  forecast: { title: "What-ifs: the business", keys: ["revenue_change_pct", "growth_change_pct_pts", "opex_change_pct"], groups: ["operations"], note: "Sales level, growth and overhead. Each other tab has its own levers." },
  receivables: {
    title: "What-ifs: receivables",
    keys: ["collection_delay_days", "past_due_delay_days", "top_customer_delay_days", "collectability_change_pts", "extra_bad_debt_pct"],
    groups: ["ar"],
    note: "How fast and how fully customers pay.",
  },
  payroll: {
    title: "What-ifs: payroll",
    keys: ["salary_change_pct", "raise_change_pct_pts", "extra_hires", "bonus_change_pct", "benefits_change_pct", "employer_tax_change_pts"],
    groups: ["payroll"],
    note: "Hiring, pay, bonuses and what each person costs on top.",
  },
  payables: {
    title: "What-ifs: payables",
    keys: ["dpo_change_days", "bill_catchup_extra_days", "top_vendor_delay_days", "cogs_change_pct_pts"],
    groups: ["payables"],
    note: "When you pay vendors and what they charge.",
  },
  capex: {
    title: "What-ifs: capex",
    keys: ["capex_change_pct", "capex_delay_months", "maintenance_capex_change_pct", "down_payment_change_pts"],
    groups: ["capex"],
    note: "Size, timing and funding of purchases.",
  },
  balance: {
    title: "What-ifs: balance sheet",
    keys: ["rate_change_pts", "tax_rate_change_pts", "extra_loan_payment", "equity_injection"],
    groups: ["financing"],
    note: "Debt, interest, tax and owner money. Every slider here moves debt, equity or cash.",
  },
  gl: {
    title: "What-ifs: ledger & other cash",
    keys: ["starting_cash_change", "other_monthly_cash", "one_time_cash_item"],
    groups: ["ledger"],
    note: "Cash the ledger or the assumptions might be missing.",
  },
  trends: {
    title: "What-ifs: trends",
    keys: ["seasonal_swing_pct", "top_customer_loss_pct", "new_sales_dso_change_days"],
    groups: ["trends"],
    note: "Seasonality, customer concentration and slower new-sale payments.",
  },
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
  bill_catchup_extra_days: "overdue bills",
  top_vendor_delay_days: "largest vendor",
  benefits_change_pct: "benefits",
  employer_tax_change_pts: "payroll taxes",
  maintenance_capex_change_pct: "maintenance capex",
  down_payment_change_pts: "down payments",
  extra_loan_payment: "loan prepayment",
  equity_injection: "owner cash",
  starting_cash_change: "starting cash",
  other_monthly_cash: "other monthly cash",
  one_time_cash_item: "one-off item",
  seasonal_swing_pct: "seasonality",
  top_customer_loss_pct: "customer loss",
  new_sales_dso_change_days: "new-sale timing",
};

export const fmtSlider = (s: Slider, v: number) => {
  if (!s.money) return `${signed(v, s.digits)} ${s.unit}`.trim();
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  return `${sign}$${Math.abs(v).toLocaleString("en-US")}${s.unit}`;
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
                    {fmtSlider(s, value)}
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
                  aria-valuetext={fmtSlider(s, value)}
                />
                <div className="text-[11px] text-[#6b7280]">{s.hint}</div>
              </div>
            );
          })}
        </div>

        {hidden.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-[#78350f] bg-[#2b1d07] px-3 py-2 text-xs text-[#fde68a]" role="status">
            <span>
              Also active on other tabs: {hidden.map((k) => `${PRESET_LABELS[k]} ${fmtSlider(SLIDER_BY_KEY[k], adjustments[k])}`).join(", ")}.
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
  selected,
  onSelect,
}: {
  ar: Forecast["ar"];
  calibration?: Defaults["data_summary"]["collections_calibration"];
  selected?: string | null;
  onSelect?: (customerId: string | null) => void;
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
              <tr key={c.customer_id} className={`border-t border-[#1a1d24] ${selected === c.customer_id ? "bg-[#12203a]" : ""}`}>
                <th scope="row" className="px-3 py-1.5 text-left font-medium text-[#e5e7eb]">
                  {onSelect ? (
                    <button
                      type="button"
                      aria-pressed={selected === c.customer_id}
                      onClick={() => onSelect(selected === c.customer_id ? null : c.customer_id)}
                      className="rounded text-left underline decoration-dotted underline-offset-2 hover:text-white"
                      title="Ask the assistant about this customer"
                    >
                      {c.customer_id}
                    </button>
                  ) : (
                    c.customer_id
                  )}
                </th>
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
