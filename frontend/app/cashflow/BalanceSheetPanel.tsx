"use client";

import { Legend, LineChart } from "./Charts";
import { cell, compact, money } from "./lib";
import { Badge, Card, Stat } from "./ui";
import type { BalanceRow, Forecast } from "./types";

type Line = { label: string; key: keyof BalanceRow; bold?: boolean; indent?: boolean };

const ASSET_LINES: Line[] = [
  { label: "Cash", key: "cash", indent: true },
  { label: "Receivables", key: "receivables", indent: true },
  { label: "Property & equipment (net)", key: "ppe_net", indent: true },
  { label: "Total assets", key: "total_assets", bold: true },
];
const LIAB_LINES: Line[] = [
  { label: "Payables", key: "payables", indent: true },
  { label: "Accrued payroll", key: "accrued_payroll", indent: true },
  { label: "Taxes payable", key: "taxes_payable", indent: true },
  { label: "Debt", key: "debt", indent: true },
  { label: "Total liabilities", key: "total_liabilities", bold: true },
  { label: "Equity", key: "equity", bold: true },
  { label: "Liabilities + equity", key: "total_liabilities_equity", bold: true },
];

export function BalanceSheetPanel({ forecast }: { forecast: Forecast }) {
  const bs = forecast.balance_sheet;
  const cols: BalanceRow[] = [bs.opening, ...bs.months];
  const last = bs.months[bs.months.length - 1] ?? bs.opening;
  const balanced = bs.max_abs_check < 0.5;
  const equityChange = last.equity - bs.opening.equity;
  const labels = cols.map((c) => c.label);
  const num = (k: keyof BalanceRow) => cols.map((c) => c[k] as number);

  const renderLines = (lines: Line[]) =>
    lines.map((l) => (
      <tr key={l.key} className={`border-t border-[#1f2937] tabular-nums ${l.bold ? "bg-[#0f1117] font-semibold" : ""}`}>
        <th scope="row" className={`sticky left-0 z-10 bg-inherit py-1.5 pr-3 text-left font-medium ${l.indent ? "pl-4 text-[#d1d5db]" : "text-[#e5e7eb]"} ${l.bold ? "bg-[#0f1117]" : "bg-[#111216]"}`}>
          {l.label}
        </th>
        {cols.map((c, i) => (
          <td key={i} className={`px-2 py-1.5 text-right ${(c[l.key] as number) < 0 ? "text-[#f87171]" : "text-[#e5e7eb]"}`}>
            {cell(c[l.key] as number)}
          </td>
        ))}
      </tr>
    ));

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Stat label="Total assets, end of plan" value={compact(last.total_assets)} sub={`Start ${compact(bs.opening.total_assets)}`} />
        <Stat label="Working capital" value={compact(last.working_capital)} tone={last.working_capital < 0 ? "bad" : "default"} sub="Cash + receivables − payables, payroll and tax owed" />
        <Stat label="Net debt" value={compact(last.net_debt)} tone={last.net_debt > 0 ? "warn" : "good"} sub="Debt minus cash (negative = net cash)" />
        <Stat label="Change in equity" value={`${equityChange >= 0 ? "+" : "-"}${compact(Math.abs(equityChange))}`} tone={equityChange < 0 ? "bad" : "good"} sub="Profit after tax and other items" />
      </div>

      <div className="flex flex-wrap items-center gap-2 text-sm">
        <Badge tone={balanced ? "good" : "bad"}>{balanced ? "Balances every month" : `Out of balance by ${money(bs.max_abs_check)}`}</Badge>
        <span className="text-xs text-[#6b7280]">Assets − liabilities − equity is checked in every column below.</span>
      </div>

      <Card title="Balance sheet projection">
        <Legend
          items={[
            { name: "Assets", color: "#60a5fa" },
            { name: "Liabilities", color: "#f87171" },
            { name: "Equity", color: "#34d399" },
            { name: "Cash", color: "#fbbf24", dashed: true },
          ]}
        />
        <LineChart
          labels={labels}
          series={[
            { name: "Assets", color: "#60a5fa", values: num("total_assets"), width: 2.4 },
            { name: "Liabilities", color: "#f87171", values: num("total_liabilities"), width: 2.4 },
            { name: "Equity", color: "#34d399", values: num("equity"), width: 2.4 },
            { name: "Cash", color: "#fbbf24", values: num("cash"), dashed: true, width: 1.8 },
          ]}
          ariaLabel="Projected total assets, liabilities, equity and cash by month"
        />
      </Card>

      <Card title="Balance sheet by month">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[900px] border-collapse text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-[#6b7280]">
                <th className="sticky left-0 z-10 bg-[#111216] py-1.5 pr-3 text-left font-medium">USD</th>
                {cols.map((c, i) => (
                  <th key={i} className="px-2 py-1.5 text-right font-medium">
                    {c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {renderLines(ASSET_LINES)}
              <tr>
                <td colSpan={cols.length + 1} className="h-2" />
              </tr>
              {renderLines(LIAB_LINES)}
              <tr className="border-t border-[#374151] tabular-nums text-xs text-[#6b7280]">
                <th scope="row" className="sticky left-0 z-10 bg-[#111216] py-1.5 pr-3 text-left font-medium">
                  Check (should be –)
                </th>
                {cols.map((c, i) => (
                  <td key={i} className="px-2 py-1.5 text-right">
                    {Math.abs(c.check) < 0.5 ? "–" : cell(c.check)}
                  </td>
                ))}
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="How to read this">
        <ul className="list-disc space-y-1.5 pl-5 text-sm leading-relaxed text-[#9ca3af]">
          <li>
            <strong className="text-[#d1d5db]">Opening column</strong> uses your starting cash, open invoices and bills, loan balances and net property and equipment; equity is what is left over.
          </li>
          <li>
            Receivables are not written down, so they include <strong className="text-[#d1d5db]">{money(bs.memo.existing_ar_expected_uncollectible)}</strong> of today&apos;s invoices and about{" "}
            <strong className="text-[#d1d5db]">{money(bs.memo.new_sales_expected_uncollectible)}</strong> of new sales that the model does not expect to collect.
          </li>
          <li>Payables and accrued payroll move with the gap between when cost is recorded and when cash leaves. Taxes are accrued at each quarter end and paid the next quarter.</li>
          <li>Debt rises with financed capex and falls by the principal part of each payment.</li>
        </ul>
      </Card>
    </div>
  );
}
