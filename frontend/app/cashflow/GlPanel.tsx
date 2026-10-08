"use client";

import { useEffect, useState } from "react";
import { Legend, LineChart } from "./Charts";
import { applyGlBaselines, cell, compact, fetchGl, money, pct, shortDate } from "./lib";
import { Badge, Card, GhostButton, Stat } from "./ui";
import type { Assumptions, Forecast, GlOverview } from "./types";

type Ledger = Exclude<GlOverview, { available: false }>;

export function GlPanel({
  forecast,
  assumptions,
  onAssumptions,
}: {
  forecast: Forecast;
  assumptions: Assumptions;
  onAssumptions: (next: Assumptions) => void;
}) {
  const [gl, setGl] = useState<GlOverview | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [applied, setApplied] = useState(false);
  const asOf = assumptions.general.as_of;

  useEffect(() => {
    const controller = new AbortController();
    fetchGl(asOf, controller.signal)
      .then((data) => {
        setGl(data);
        setError(null);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Couldn't load the ledger");
      });
    return () => controller.abort();
  }, [asOf]);

  if (error) {
    return (
      <p role="alert" className="rounded-xl border border-[#7f1d1d] bg-[#2a0f14] px-4 py-3 text-sm text-[#fecaca]">
        Couldn&apos;t load the general ledger: {error}
      </p>
    );
  }
  if (!gl) return <p className="text-sm text-[#9ca3af]" role="status">Loading the general ledger…</p>;
  if (gl.available === false) {
    return (
      <Card title="General ledger">
        <p className="text-sm text-[#d1d5db]">No general ledger is loaded on the server, so there are no actuals to compare with.</p>
      </Card>
    );
  }
  const ledger: Ledger = gl;
  const cmp = forecast.gl;
  const tl = cmp?.timeline ?? [];
  const labels = tl.map((t) => t.label);
  const recent = ledger.monthly.filter((m) => !m.partial).slice(-12);
  const tieOk = ledger.tie_out.every((t) => t.ok);
  const bl = ledger.baselines;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Stat label="Ledger cash" value={compact(bl?.starting_cash ?? 0)} sub={`At ${shortDate(ledger.as_of)}`} />
        <Stat label="Receivables / payables" value={`${compact(bl?.receivables ?? 0)} / ${compact(bl?.payables ?? 0)}`} sub="From the ledger balances" />
        <Stat label="Journal" value={`${ledger.entry_count.toLocaleString()} entries`} sub={`${shortDate(ledger.first_date)} → ${shortDate(ledger.last_date)}`} />
        <Stat
          label="Trial balance"
          value={ledger.trial_balance.balanced ? "Balanced" : "Out of balance"}
          tone={ledger.trial_balance.balanced ? "good" : "bad"}
          sub={`Debits ${compact(ledger.trial_balance.total_debit)} = credits ${compact(ledger.trial_balance.total_credit)}`}
        />
      </div>

      <Card title="Actuals vs forecast" right={<Badge tone="blue">Solid = ledger, dashed = forecast</Badge>}>
        <Legend
          items={[
            { name: "Revenue (actual)", color: "#60a5fa" },
            { name: "Revenue (forecast)", color: "#60a5fa", dashed: true },
            { name: "Pre-tax profit (actual)", color: "#34d399" },
            { name: "Pre-tax profit (forecast)", color: "#34d399", dashed: true },
          ]}
        />
        <LineChart
          labels={labels}
          series={[
            { name: "Revenue (actual)", color: "#60a5fa", values: tl.map((t) => t.actual_revenue), width: 2.6 },
            { name: "Revenue (forecast)", color: "#60a5fa", values: tl.map((t) => t.forecast_revenue), dashed: true },
            { name: "Pre-tax profit (actual)", color: "#34d399", values: tl.map((t) => t.actual_pretax), width: 2.6 },
            { name: "Pre-tax profit (forecast)", color: "#34d399", values: tl.map((t) => t.forecast_pretax), dashed: true },
          ]}
          ariaLabel="Monthly revenue and pre-tax profit: ledger actuals followed by the forecast"
        />
        <p className="mt-2 text-xs text-[#6b7280]">
          The month containing the start date is partial in the ledger, so it is left out of the actuals.
          {cmp && cmp.variance.length > 0 ? " Months where the forecast overlaps real results are compared below." : " Move the forecast start date back to see how the forecast would have compared with real results."}
        </p>
      </Card>

      <div className="grid gap-5 2xl:grid-cols-2">
        <Card
          title="Forecast starting point vs ledger"
          right={
            bl && (
              <GhostButton
                onClick={() => {
                  onAssumptions(applyGlBaselines(assumptions, bl));
                  setApplied(true);
                }}
                title="Set starting cash, revenue, cost of sales, operating expenses, the term loan and depreciation from the ledger"
              >
                {applied ? "Applied ✓" : "Apply ledger baselines"}
              </GhostButton>
            )
          }
        >
          <p className="mb-2 text-xs text-[#6b7280]">
            Average of {cmp?.baseline_window.join(", ") || "the last three complete months"} against the forecast&apos;s first month.
          </p>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-[#6b7280]">
                <th className="py-1.5 pr-3 font-medium">Line</th>
                <th className="py-1.5 pr-3 text-right font-medium">Ledger avg</th>
                <th className="py-1.5 pr-3 text-right font-medium">Forecast</th>
                <th className="py-1.5 text-right font-medium">Diff</th>
              </tr>
            </thead>
            <tbody>
              {(cmp?.baseline_check ?? []).map((r) => {
                const big = r.difference_pct !== null && Math.abs(r.difference_pct) > 10;
                return (
                  <tr key={r.label} className="border-t border-[#1f2937] tabular-nums">
                    <td className="py-1.5 pr-3 text-[#d1d5db]">{r.label}</td>
                    <td className="py-1.5 pr-3 text-right">{money(r.actual_avg)}</td>
                    <td className="py-1.5 pr-3 text-right">{money(r.forecast_first_month)}</td>
                    <td className={`py-1.5 text-right ${big ? "text-[#fbbf24]" : "text-[#9ca3af]"}`}>
                      {r.difference_pct === null ? "–" : `${r.difference_pct > 0 ? "+" : ""}${pct(r.difference_pct)}`}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-2 text-xs leading-snug text-[#6b7280]">
            Differences over 10% come from your edits or the selected scenario (the best and worst cases move revenue and costs). Payroll comes from the roster, not the ledger.
          </p>
        </Card>

        <Card title="Ledger ties to the sub-ledgers" right={<Badge tone={tieOk ? "good" : "bad"}>{tieOk ? "All tie" : "Differences found"}</Badge>}>
          <table className="w-full text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-[#6b7280]">
                <th className="py-1.5 pr-3 font-medium">Check</th>
                <th className="py-1.5 pr-3 text-right font-medium">Ledger</th>
                <th className="py-1.5 pr-3 text-right font-medium">Source</th>
                <th className="py-1.5 text-right font-medium" />
              </tr>
            </thead>
            <tbody>
              {ledger.tie_out.map((t) => (
                <tr key={t.label} className="border-t border-[#1f2937] tabular-nums">
                  <td className="py-1.5 pr-3 text-[#d1d5db]">{t.label}</td>
                  <td className="py-1.5 pr-3 text-right">{money(t.ledger)}</td>
                  <td className="py-1.5 pr-3 text-right">{money(t.source)}</td>
                  <td className="py-1.5 text-right">
                    <Badge tone={t.ok ? "good" : "bad"}>{t.ok ? "ties" : money(t.difference)}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      {cmp && cmp.variance.length > 0 && (
        <Card title="Variance: forecast vs actual">
          <div className="grid gap-4 md:grid-cols-2">
            {cmp.variance.slice(0, 6).map((v) => (
              <div key={v.label}>
                <div className="mb-1 text-sm font-semibold text-[#e5e7eb]">{v.label}{v.approximate && <span className="ml-1 text-xs font-normal text-[#6b7280]">(approx. window)</span>}</div>
                <table className="w-full text-xs tabular-nums">
                  <tbody>
                    {v.lines.map((l) => (
                      <tr key={l.label} className="border-t border-[#1f2937]">
                        <td className="py-1 text-[#9ca3af]">{l.label}</td>
                        <td className="py-1 text-right">{cell(l.actual)}</td>
                        <td className="py-1 text-right text-[#6b7280]">{cell(l.forecast)}</td>
                        <td className={`py-1 text-right ${l.variance < 0 ? "text-[#f87171]" : "text-[#34d399]"}`}>{cell(l.variance)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ))}
          </div>
          <p className="mt-2 text-xs text-[#6b7280]">Columns: actual, forecast, actual − forecast.</p>
        </Card>
      )}

      <Card title="Monthly results from the ledger">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-[#6b7280]">
                <th className="py-1.5 pr-3 text-left font-medium">Month</th>
                {["Revenue", "Cost of sales", "Payroll", "Opex", "Deprec.", "Interest", "Pre-tax"].map((h) => (
                  <th key={h} className="px-2 py-1.5 text-right font-medium">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {recent.map((m) => (
                <tr key={m.month} className="border-t border-[#1f2937] tabular-nums">
                  <td className="py-1.5 pr-3 text-[#e5e7eb]">{m.label}</td>
                  {[m.revenue, m.cogs, m.payroll, m.opex, m.depreciation, m.interest, m.pretax_profit].map((v, i) => (
                    <td key={i} className={`px-2 py-1.5 text-right ${i === 6 && v < 0 ? "text-[#f87171]" : ""}`}>{cell(v)}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title={`Trial balance at ${shortDate(ledger.as_of)}`}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-sm">
            <thead>
              <tr className="text-xs uppercase tracking-wide text-[#6b7280]">
                <th className="py-1.5 pr-3 text-left font-medium">Account</th>
                <th className="py-1.5 pr-3 text-left font-medium">Type</th>
                <th className="py-1.5 pr-3 text-right font-medium">Debit</th>
                <th className="py-1.5 text-right font-medium">Credit</th>
              </tr>
            </thead>
            <tbody>
              {ledger.trial_balance.rows.map((r) => (
                <tr key={r.account_id} className="border-t border-[#1f2937] tabular-nums">
                  <td className="py-1.5 pr-3 text-[#e5e7eb]"><span className="mr-2 text-[#6b7280]">{r.account_id}</span>{r.name}</td>
                  <td className="py-1.5 pr-3 text-[#9ca3af]">{r.type}</td>
                  <td className="py-1.5 pr-3 text-right">{cell(r.debit_balance)}</td>
                  <td className="py-1.5 text-right">{cell(r.credit_balance)}</td>
                </tr>
              ))}
              <tr className="border-t border-[#374151] bg-[#0f1117] font-semibold tabular-nums">
                <td className="py-1.5 pr-3" colSpan={2}>Total</td>
                <td className="py-1.5 pr-3 text-right">{cell(ledger.trial_balance.total_debit)}</td>
                <td className="py-1.5 text-right">{cell(ledger.trial_balance.total_credit)}</td>
              </tr>
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Latest journal lines">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-xs">
            <thead>
              <tr className="uppercase tracking-wide text-[#6b7280]">
                <th className="py-1.5 pr-3 text-left font-medium">Date</th>
                <th className="py-1.5 pr-3 text-left font-medium">Entry</th>
                <th className="py-1.5 pr-3 text-left font-medium">Account</th>
                <th className="py-1.5 pr-3 text-left font-medium">Memo</th>
                <th className="py-1.5 pr-3 text-right font-medium">Debit</th>
                <th className="py-1.5 text-right font-medium">Credit</th>
              </tr>
            </thead>
            <tbody>
              {ledger.recent_entries.slice(-14).map((e, i) => (
                <tr key={i} className="border-t border-[#1f2937] tabular-nums">
                  <td className="py-1 pr-3 text-[#9ca3af]">{shortDate(e.date)}</td>
                  <td className="py-1 pr-3 text-[#6b7280]">{e.entry}</td>
                  <td className="py-1 pr-3 text-[#d1d5db]">{e.account}</td>
                  <td className="py-1 pr-3 text-[#9ca3af]">{e.memo}</td>
                  <td className="py-1 pr-3 text-right">{cell(e.debit)}</td>
                  <td className="py-1 text-right">{cell(e.credit)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-[#6b7280]">
          Sample ledger generated from the same invoices, bills and payroll roster as the rest of the model. Replace it with your own export to use real books.
        </p>
      </Card>
    </div>
  );
}
