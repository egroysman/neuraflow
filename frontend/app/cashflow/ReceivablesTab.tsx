"use client";

import { Legend, StackedBars } from "./Charts";
import { compact, money, pct } from "./lib";
import { ReceivablesPanel } from "./Panels";
import { Card, Stat } from "./ui";
import type { Adjustments, Defaults, Forecast } from "./types";

const EXISTING = "#60a5fa";
const NEW_SALES = "#34d399";

export function ReceivablesTab({
  forecast,
  adjustments,
  calibration,
  focus,
  onFocus,
}: {
  forecast: Forecast;
  adjustments: Adjustments;
  focus: string | null;
  onFocus: (id: string | null) => void;
  calibration?: Defaults["data_summary"]["collections_calibration"];
}) {
  const ar = forecast.ar;
  const impact = forecast.whatif_impact.ar;
  const months = forecast.monthly;
  const weeks = forecast.weekly;
  const existingM = months.map((p) => p.categories.ar_collections || 0);
  const newM = months.map((p) => p.categories.new_sales_collections || 0);
  const existingW = weeks.map((p) => p.categories.ar_collections || 0);
  const newW = weeks.map((p) => p.categories.new_sales_collections || 0);
  const collected = existingM.reduce((a, b) => a + b, 0) + newM.reduce((a, b) => a + b, 0);
  const pastDue = ar.aging.filter((a) => a.bucket !== "current").reduce((s, a) => s + a.open_amount, 0);
  const pastDuePct = ar.open_total ? (pastDue / ar.open_total) * 100 : 0;
  const haircutPct = ar.open_total ? (ar.expected_haircut / ar.open_total) * 100 : 0;
  const inHorizonPct = ar.open_total ? (ar.expected_in_horizon / ar.open_total) * 100 : 0;
  const top = ar.customers.reduce((best, c) => (c.open_amount > (best?.open_amount ?? 0) ? c : best), ar.customers[0]);
  const topShare = top && ar.open_total ? (top.open_amount / ar.open_total) * 100 : 0;
  const activeWhatIfs = (["collection_delay_days", "past_due_delay_days", "top_customer_delay_days", "collectability_change_pts", "extra_bad_debt_pct"] as const).filter(
    (k) => adjustments[k] !== 0
  );

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Stat label="Open receivables" value={compact(ar.open_total)} sub={`${pct(pastDuePct, 0)} past due · ${compact(pastDue)}`} tone={pastDuePct >= 40 ? "warn" : "default"} />
        <Stat
          label="Expected in the plan window"
          value={compact(ar.expected_in_horizon)}
          sub={`${pct(inHorizonPct, 0)} of open invoices collected within the horizon`}
        />
        <Stat
          label="Not expected to be collected"
          value={compact(ar.expected_haircut)}
          tone={haircutPct >= 15 ? "bad" : haircutPct >= 5 ? "warn" : "default"}
          sub={`${pct(haircutPct, 0)} of open invoices after collectability`}
        />
        <Stat
          label="Collected from customers"
          value={compact(collected)}
          sub={`${compact(existingM.reduce((a, b) => a + b, 0))} from today's invoices + ${compact(newM.reduce((a, b) => a + b, 0))} from new sales`}
        />
      </div>

      {impact.active && (
        <p role="status" className="rounded-xl border border-[#1e3a8a] bg-[#0c1a33] px-4 py-3 text-sm text-[#bfdbfe]">
          Your receivables what-ifs ({activeWhatIfs.length} active) change ending cash by{" "}
          <strong className={impact.ending_cash_impact < 0 ? "text-[#fca5a5]" : "text-[#6ee7b7]"}>
            {impact.ending_cash_impact >= 0 ? "+" : "-"}{money(Math.abs(impact.ending_cash_impact))}
          </strong>{" "}
          and the lowest balance by{" "}
          <strong className={impact.lowest_balance_impact < 0 ? "text-[#fca5a5]" : "text-[#6ee7b7]"}>
            {impact.lowest_balance_impact >= 0 ? "+" : "-"}{money(Math.abs(impact.lowest_balance_impact))}
          </strong>
          .
        </p>
      )}

      {top && topShare >= 25 && (
        <p role="status" className="rounded-xl border border-[#78350f] bg-[#2b1d07] px-4 py-3 text-sm text-[#fde68a]">
          {top.customer_id} owes {money(top.open_amount)}, {pct(topShare, 0)} of open receivables. Use <strong>Largest customer pays later</strong> to see what a slow payment would do.
        </p>
      )}

      <div className="grid gap-5 2xl:grid-cols-2">
        <Card title="Customer cash by month">
          <Legend items={[{ name: "Invoices open today", color: EXISTING }, { name: "New sales", color: NEW_SALES }]} />
          <StackedBars
            labels={months.map((p) => p.label)}
            series={[
              { name: "Invoices open today", color: EXISTING, values: existingM },
              { name: "New sales", color: NEW_SALES, values: newM },
            ]}
            ariaLabel="Monthly cash collected from customers, split between invoices already open and new sales"
          />
        </Card>
        <Card title="Next 13 weeks">
          <Legend items={[{ name: "Invoices open today", color: EXISTING }, { name: "New sales", color: NEW_SALES }]} />
          <StackedBars
            labels={weeks.map((p) => p.label)}
            series={[
              { name: "Invoices open today", color: EXISTING, values: existingW },
              { name: "New sales", color: NEW_SALES, values: newW },
            ]}
            ariaLabel="Weekly cash collected from customers over the next 13 weeks"
          />
        </Card>
      </div>

      <ReceivablesPanel ar={ar} calibration={calibration} selected={focus} onSelect={onFocus} />
    </div>
  );
}
