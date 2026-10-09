"use client";

import { money, shortDate } from "./lib";
import { Card } from "./ui";
import type { Forecast } from "./types";

const signed = (v: number) => `${v >= 0 ? "+" : "-"}${money(Math.abs(v))}`;

/** Where cash stands after 30, 60, 90 and 180 days and 1 year. */
export function ProjectionsCard({ forecast, minCash }: { forecast: Forecast; minCash: number }) {
  const rows = forecast.projections;
  const scenarios = Object.entries(forecast.comparison);
  const status = (p: Forecast["projections"][number]) =>
    p.first_negative_date ? { text: "Runs out of cash", cls: "text-[#f87171]" } : p.lowest_balance < minCash ? { text: "Below minimum", cls: "text-[#fbbf24]" } : { text: "Above minimum", cls: "text-[#34d399]" };

  return (
    <Card title="Standard projections" right={<span className="text-xs text-[#9ca3af]">From {shortDate(forecast.as_of)} · {forecast.scenario_label}</span>}>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] text-sm" data-testid="projections-table">
          <caption className="sr-only">Cash position at 30, 60, 90 and 180 days and 1 year</caption>
          <thead>
            <tr className="text-xs text-[#9ca3af]">
              <th scope="col" className="px-3 py-2 text-left font-medium">&nbsp;</th>
              {rows.map((p) => (
                <th key={p.days} scope="col" className="px-3 py-2 text-right font-medium">
                  {p.label}
                  <div className="font-normal text-[#6b7280]">{shortDate(p.end_date)}</div>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular-nums">
            <tr className="border-t border-[#1a1d24]">
              <th scope="row" className="px-3 py-1.5 text-left font-semibold text-[#e5e7eb]">Ending cash</th>
              {rows.map((p) => (
                <td key={p.days} className={`px-3 py-1.5 text-right font-semibold ${p.ending_cash < 0 ? "text-[#f87171]" : "text-[#e5e7eb]"}`}>
                  {p.complete ? money(p.ending_cash) : "n/a"}
                </td>
              ))}
            </tr>
            <tr className="border-t border-[#1a1d24]">
              <th scope="row" className="px-3 py-1.5 text-left font-medium text-[#9ca3af]">Change from today</th>
              {rows.map((p) => (
                <td key={p.days} className="px-3 py-1.5 text-right">{p.complete ? signed(p.net_cash_flow) : "n/a"}</td>
              ))}
            </tr>
            <tr className="border-t border-[#1a1d24]">
              <th scope="row" className="px-3 py-1.5 text-left font-medium text-[#9ca3af]">Cash in</th>
              {rows.map((p) => (
                <td key={p.days} className="px-3 py-1.5 text-right">{p.complete ? money(p.cash_in) : "n/a"}</td>
              ))}
            </tr>
            <tr className="border-t border-[#1a1d24]">
              <th scope="row" className="px-3 py-1.5 text-left font-medium text-[#9ca3af]">Cash out</th>
              {rows.map((p) => (
                <td key={p.days} className="px-3 py-1.5 text-right">{p.complete ? money(p.cash_out) : "n/a"}</td>
              ))}
            </tr>
            <tr className="border-t border-[#1a1d24]">
              <th scope="row" className="px-3 py-1.5 text-left font-medium text-[#9ca3af]">Operating / investing / financing</th>
              {rows.map((p) => (
                <td key={p.days} className="px-3 py-1.5 text-right text-xs text-[#9ca3af]">
                  {p.complete ? `${signed(p.operating)} / ${signed(p.investing)} / ${signed(p.financing)}` : "n/a"}
                </td>
              ))}
            </tr>
            <tr className="border-t border-[#1a1d24]">
              <th scope="row" className="px-3 py-1.5 text-left font-medium text-[#9ca3af]">Lowest balance</th>
              {rows.map((p) => (
                <td key={p.days} className="px-3 py-1.5 text-right">
                  {p.complete ? money(p.lowest_balance) : "n/a"}
                  {p.complete && <div className="text-xs text-[#6b7280]">{shortDate(p.lowest_balance_date)}</div>}
                </td>
              ))}
            </tr>
            <tr className="border-t border-[#1a1d24]">
              <th scope="row" className="px-3 py-1.5 text-left font-medium text-[#9ca3af]">Status</th>
              {rows.map((p) => {
                const s = status(p);
                return (
                  <td key={p.days} className={`px-3 py-1.5 text-right text-xs font-semibold ${p.complete ? s.cls : "text-[#6b7280]"}`}>
                    {p.complete ? s.text : "Past model horizon"}
                  </td>
                );
              })}
            </tr>
            <tr className="border-t border-[#2a2f3a]">
              <th scope="row" colSpan={rows.length + 1} className="px-3 pb-1 pt-3 text-left text-xs font-medium uppercase tracking-wide text-[#6b7280]">
                Ending cash by scenario
              </th>
            </tr>
            {scenarios.map(([key, s]) => (
              <tr key={key} className={key === forecast.scenario ? "bg-[#12203a]" : ""}>
                <th scope="row" className="px-3 py-1.5 text-left font-medium text-[#9ca3af]">{s.label}</th>
                {s.projection_end_cash.map((v, i) => (
                  <td key={i} className={`px-3 py-1.5 text-right ${v < 0 ? "text-[#f87171]" : ""}`}>{rows[i].complete ? money(v) : "n/a"}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.some((p) => !p.complete) && (
        <p className="mt-2 text-xs text-[#9ca3af]">Longer windows need a longer plan horizon. Raise it in General settings to see them.</p>
      )}
    </Card>
  );
}
