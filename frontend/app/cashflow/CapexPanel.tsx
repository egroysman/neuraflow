"use client";

import { LineChart, Legend, StackedBars } from "./Charts";
import { money, pct, shortDate } from "./lib";
import { Badge, COLORS, Card, Stat } from "./ui";
import type { CapexResult } from "./types";

const FUNDING_LABEL = { cash: "Cash", loan: "Loan", lease: "Lease" } as const;

export function CapexPanel({ capex, horizon }: { capex: CapexResult; horizon: number }) {
  const t = capex.totals;
  const labels = capex.monthly.map((m) => m.label);
  const scaled = Math.abs(t.growth_scale - 1) > 0.005;

  return (
    <div className="space-y-5">
      {scaled && (
        <p role="status" className="rounded-xl border border-[#1e3a8a] bg-[#0c1a33] px-4 py-3 text-sm text-[#bfdbfe]">
          In this scenario growth capex runs at {pct(t.growth_scale * 100, 0)} of plan (it follows scenario sales and the capex slider). Maintenance capex is unchanged.
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Stat label={`Cash capex, ${horizon} mo`} value={money(t.cash_capex)} sub={`Maintenance ${money(t.maintenance)} · growth ${money(t.growth)}`} />
        <Stat label="Financed purchases" value={money(t.financed_amount)} sub="Loans and leases (down payment paid in cash)" />
        <Stat label="Financing payments" value={money(t.financed_payments)} sub={`${money(t.interest)} of it is interest`} />
        <Stat label="Depreciation (non-cash)" value={money(t.depreciation)} sub="Lowers profit and tax, not cash" />
      </div>

      <div className="grid gap-5 2xl:grid-cols-2">
        <Card title="Capex cash out by month">
          <Legend
            items={[
              { name: "Maintenance", color: COLORS.blue },
              { name: "Growth", color: "#a78bfa" },
              { name: "Loan / lease payments", color: COLORS.amber },
            ]}
          />
          <StackedBars
            labels={labels}
            series={[
              { name: "Maintenance", color: COLORS.blue, values: capex.monthly.map((m) => m.maintenance) },
              { name: "Growth", color: "#a78bfa", values: capex.monthly.map((m) => m.growth) },
              { name: "Loan / lease payments", color: COLORS.amber, values: capex.monthly.map((m) => m.financed_payments) },
            ]}
            ariaLabel="Capital spending each month split into maintenance, growth and financing payments"
          />
        </Card>
        <Card title="Net asset additions (cumulative)">
          <Legend items={[{ name: "Additions less depreciation", color: COLORS.green }]} />
          <LineChart
            labels={labels}
            series={[{ name: "Net additions", color: COLORS.green, values: capex.monthly.map((m) => m.net_additions_cum) }]}
            ariaLabel="Cumulative capital additions less depreciation across the forecast"
          />
          <p className="mt-2 text-xs text-[#6b7280]">New capex minus depreciation since the start date (existing assets are not included).</p>
        </Card>
      </div>

      <Card title="Capex plan">
        <div className="overflow-x-auto rounded-lg border border-[#1f2937]">
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">Planned capital purchases with funding and depreciation</caption>
            <thead>
              <tr className="bg-[#0b0b0f] text-xs text-[#9ca3af]">
                {["Item", "Date", "Type", "Funding", "Amount", "Cash at purchase", "Financed", "Payment / mo", "Depreciation / mo"].map((h, i) => (
                  <th key={h} scope="col" className={`whitespace-nowrap px-3 py-2 font-medium ${i < 4 ? "text-left" : "text-right"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {capex.items.map((it, i) => (
                <tr key={`${it.name}-${i}`} className={`border-t border-[#1a1d24] ${it.in_horizon ? "" : "opacity-50"}`}>
                  <th scope="row" className="px-3 py-1.5 text-left font-medium text-[#e5e7eb]">
                    {it.name}
                    {!it.in_horizon && <span className="ml-2 text-[11px] font-normal text-[#fbbf24]">outside horizon</span>}
                  </th>
                  <td className="px-3 py-1.5 text-left tabular-nums">{shortDate(it.date)}</td>
                  <td className="px-3 py-1.5 text-left"><Badge tone={it.kind === "growth" ? "blue" : "neutral"}>{it.kind}</Badge></td>
                  <td className="px-3 py-1.5 text-left text-[#d1d5db]">{FUNDING_LABEL[it.funding]}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {money(it.amount)}
                    {Math.abs(it.amount - it.planned_amount) > 0.5 && <div className="text-[10px] text-[#6b7280]">plan {money(it.planned_amount)}</div>}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{it.in_horizon ? money(it.cash_at_purchase) : "–"}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{it.financed > 0 ? money(it.financed) : "–"}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{it.monthly_payment > 0 ? money(it.monthly_payment) : "–"}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{money(it.depreciation_monthly)}</td>
                </tr>
              ))}
              {capex.items.length === 0 && (
                <tr><td colSpan={9} className="px-3 py-4 text-center text-[#6b7280]">No capex items yet. Add purchases under Assumptions → Capex plan.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs leading-snug text-[#6b7280]">
          Financed items pay only the down payment on the purchase date, then level monthly loan or lease payments. Depreciation is straight-line from the month of purchase.
        </p>
      </Card>
    </div>
  );
}
