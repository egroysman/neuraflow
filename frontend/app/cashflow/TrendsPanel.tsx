"use client";

import { useEffect, useMemo, useState } from "react";
import { LineChart, Legend, Sparkline } from "./Charts";
import { fetchMacro, fetchTrends, fmtUnit, money, parseDate, pct, signed } from "./lib";
import { Badge, COLORS, Card, Field, GhostButton, NumInput, Stat } from "./ui";
import type { Assumptions, MacroData, MacroEffect, MacroInputs, MacroSeries, TrendSignal, Trends } from "./types";

const message = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");
const TONE_COLOR = { good: "text-[#34d399]", bad: "text-[#f87171]", neutral: "text-[#9ca3af]" } as const;
const ARROW = (v: number) => (v > 0 ? "▲" : v < 0 ? "▼" : "■");

function SignalCard({ s }: { s: TrendSignal }) {
  const changeText = s.change_unit === "%" ? `${signed(s.change, 1)}%` : `${signed(s.change, s.unit === "days" ? 0 : 1)} ${s.change_unit}`;
  return (
    <div className="rounded-xl border border-[#1f2937] bg-[#111216] p-3.5">
      <div className="text-xs font-medium text-[#9ca3af]">{s.label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-xl font-bold tabular-nums text-[#e5e7eb]">{fmtUnit(s.current, s.unit)}</span>
        <span className={`text-sm font-semibold tabular-nums ${TONE_COLOR[s.tone]}`}>
          <span aria-hidden>{ARROW(s.change)} </span>
          {changeText}
          <span className="sr-only"> ({s.tone === "good" ? "favourable" : s.tone === "bad" ? "unfavourable" : "flat"})</span>
        </span>
      </div>
      <div className="mt-0.5 text-[11px] leading-snug text-[#6b7280]">
        Last {s.window_months} mo vs prior {s.window_months} (was {fmtUnit(s.previous, s.unit)}).{s.note ? ` ${s.note}.` : ""}
      </div>
    </div>
  );
}

function MicroTrends({
  assumptions,
  onApply,
}: {
  assumptions: Assumptions;
  onApply: (patch: { growth?: number; dso?: number }) => void;
}) {
  const [data, setData] = useState<Trends | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const c = new AbortController();
    fetchTrends(c.signal).then(setData).catch((e) => !c.signal.aborted && setError(message(e)));
    return () => c.abort();
  }, []);

  const months = useMemo(() => (data ? data.months.filter((m) => !m.partial) : []), [data]);
  const charts = useMemo(() => {
    const labels = months.map((m) => m.label);
    const days = months.filter((m) => m.avg_days_to_pay !== null);
    const rates = months.filter((m) => m.on_time_pct !== null && m.past_due_pct !== null);
    return {
      money: {
        labels,
        series: [
          { name: "Invoiced", color: COLORS.blue, values: months.map((m) => m.invoiced) },
          { name: "Collected", color: COLORS.green, values: months.map((m) => m.collected) },
          { name: "Vendor bills", color: COLORS.amber, values: months.map((m) => m.vendor_billed), dashed: true },
        ],
      },
      days: {
        labels: days.map((m) => m.label),
        series: [
          { name: "Customers pay you", color: COLORS.green, values: days.map((m) => m.avg_days_to_pay as number) },
          { name: "You pay vendors", color: COLORS.amber, values: days.map((m) => m.vendor_days_to_pay ?? 0), dashed: true },
        ],
      },
      rates: {
        labels: rates.map((m) => m.label),
        series: [
          { name: "Paid on time", color: COLORS.green, values: rates.map((m) => m.on_time_pct as number) },
          { name: "Receivables past due", color: COLORS.red, values: rates.map((m) => m.past_due_pct as number) },
        ],
      },
    };
  }, [months]);

  if (error) {
    return (
      <Card title="Company trends">
        <p role="alert" className="text-sm text-[#fecaca]">Couldn&apos;t load trends: {error}</p>
      </Card>
    );
  }
  if (!data) return <p className="text-sm text-[#9ca3af]" role="status">Reading your invoice and bill history…</p>;

  const growth = data.implied.growth;
  const dso = data.implied.days_to_pay;
  const modelGrowth = assumptions.sales.growth_pct_monthly;
  const modelDso = assumptions.sales.dso_days;
  const growthDiff = growth ? growth.monthly_growth_pct - modelGrowth : 0;
  const dsoDiff = dso !== null ? dso - modelDso : 0;

  return (
    <div className="space-y-5">
      <div>
        <h2 className="m-0 text-lg font-semibold">Micro trends: what your own data says</h2>
        <p className="mt-1 text-sm text-[#9ca3af]">
          From {data.months.length} months of invoices and vendor bills up to {parseDate(data.as_of).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })}. Green is favourable for cash, red is not.
        </p>
      </div>

      {data.signals.length > 0 ? (
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {data.signals.map((s) => <SignalCard key={s.key} s={s} />)}
        </div>
      ) : (
        <p className="rounded-xl border border-[#1f2937] bg-[#111216] px-4 py-3 text-sm text-[#9ca3af]">
          Not enough complete months to compare periods yet.
        </p>
      )}

      <div className="grid gap-5 2xl:grid-cols-2">
        <Card title="Revenue, collections and vendor bills">
          <Legend items={charts.money.series.map((s) => ({ name: s.name, color: s.color, dashed: s.dashed }))} />
          <LineChart labels={charts.money.labels} series={charts.money.series} ariaLabel="Monthly invoiced revenue, cash collected and vendor bills" />
        </Card>
        <Card title="Days to get paid vs days to pay">
          <Legend items={charts.days.series.map((s) => ({ name: s.name, color: s.color, dashed: s.dashed }))} />
          <LineChart
            labels={charts.days.labels}
            series={charts.days.series}
            axisFormat={(v) => `${Math.round(v)} d`}
            valueFormat={(v) => `${v.toFixed(0)} days`}
            ariaLabel="Average days customers take to pay you versus days you take to pay vendors"
          />
          <p className="mt-2 text-xs text-[#6b7280]">A widening gap (customers slower, you faster) squeezes cash.</p>
        </Card>
        <Card title="Payment quality">
          <Legend items={charts.rates.series.map((s) => ({ name: s.name, color: s.color }))} />
          <LineChart
            labels={charts.rates.labels}
            series={charts.rates.series}
            axisFormat={(v) => `${Math.round(v)}%`}
            valueFormat={(v) => `${v.toFixed(1)}%`}
            ariaLabel="Share of invoices paid on time and share of receivables past due, by month"
          />
        </Card>

        <Card title="Your data vs the model">
          <div className="space-y-4 text-sm">
            <div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium text-[#e5e7eb]">Monthly revenue growth</span>
                {growth && (
                  <GhostButton onClick={() => onApply({ growth: Math.round(growth.monthly_growth_pct * 10) / 10 })} title="Set the growth assumption to the trend in your data">
                    Use data trend
                  </GhostButton>
                )}
              </div>
              {growth ? (
                <p className="mt-1 text-[#9ca3af]">
                  Data trend <strong className="tabular-nums text-[#e5e7eb]">{signed(growth.monthly_growth_pct, 1)}%/mo</strong> (fit over {growth.months_used} complete months) vs model{" "}
                  <strong className="tabular-nums text-[#e5e7eb]">{signed(modelGrowth, 1)}%/mo</strong>.{" "}
                  {Math.abs(growthDiff) >= 1 && <Badge tone="warn">{growthDiff > 0 ? "Model is below the data" : "Model is above the data"}</Badge>}
                </p>
              ) : (
                <p className="mt-1 text-[#6b7280]">Needs at least 4 complete months.</p>
              )}
              <p className="mt-1 text-xs text-[#6b7280]">A short history makes this noisy; treat it as a sanity check, not a forecast.</p>
            </div>
            <div>
              <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="font-medium text-[#e5e7eb]">Days to collect (DSO)</span>
                {dso !== null && (
                  <GhostButton onClick={() => onApply({ dso: Math.round(dso) })} title="Set DSO to the average days your customers actually take to pay">
                    Use data value
                  </GhostButton>
                )}
              </div>
              {dso !== null && (
                <p className="mt-1 text-[#9ca3af]">
                  Customers took <strong className="tabular-nums text-[#e5e7eb]">{dso.toFixed(0)} days</strong> to pay vs model <strong className="tabular-nums text-[#e5e7eb]">{modelDso.toFixed(0)}</strong>.{" "}
                  {Math.abs(dsoDiff) >= 5 && <Badge tone="warn">{dsoDiff > 0 ? "Model is optimistic" : "Model is cautious"}</Badge>}
                </p>
              )}
            </div>
            <div>
              <span className="font-medium text-[#e5e7eb]">Customer concentration</span>
              <p className="mt-1 text-[#9ca3af]">
                Top customer <strong className="tabular-nums text-[#e5e7eb]">{data.concentration.top1_pct}%</strong> and top 5{" "}
                <strong className="tabular-nums text-[#e5e7eb]">{data.concentration.top5_pct}%</strong> of the last {data.concentration.window_months} months&apos; invoicing ({data.concentration.customers} customers).
              </p>
            </div>
            <div>
              <span className="font-medium text-[#e5e7eb]">Seasonality</span>
              <p className="mt-1 text-[#6b7280]">{data.seasonality ? "Seasonal index available." : data.seasonality_note}</p>
            </div>
          </div>
        </Card>
      </div>

      <ul className="space-y-1 text-xs text-[#6b7280]">
        {data.caveats.map((c) => <li key={c}>• {c}</li>)}
      </ul>
    </div>
  );
}

/* ----------------------------------------------------------------- Macro */

const MACRO_FIELDS: {
  key: "rate_change_pts" | "cost_inflation_pct" | "demand_growth_pct";
  label: string;
  unit: string;
  min: number;
  max: number;
  hint: string;
}[] = [
  { key: "rate_change_pts", label: "Interest rates", unit: "pts", min: -10, max: 10, hint: "Added to floating-rate loans and new financed capex" },
  { key: "cost_inflation_pct", label: "Cost inflation", unit: "% / yr", min: -10, max: 30, hint: "Extra annual growth on fixed opex and salaries" },
  { key: "demand_growth_pct", label: "Demand growth", unit: "% / yr", min: -30, max: 30, hint: "Extra annual growth on new sales" },
];

const STATUS: Record<MacroData["status"], { text: string; tone: "good" | "warn" | "bad" }> = {
  live: { text: "Live", tone: "good" },
  partial: { text: "Partly live", tone: "warn" },
  stale: { text: "Showing last saved data", tone: "warn" },
  unavailable: { text: "Unavailable", tone: "bad" },
};

function MacroCard({ s }: { s: MacroSeries }) {
  const up = (s.change_12m ?? 0) > 0;
  return (
    <div className="rounded-xl border border-[#1f2937] bg-[#111216] p-3.5">
      <div className="text-xs font-medium text-[#9ca3af]">{s.label}</div>
      <div className="mt-1 flex items-baseline gap-2">
        <span className="text-xl font-bold tabular-nums text-[#e5e7eb]">{pct(s.latest, 2)}</span>
        {s.change_12m !== null && (
          <span className="text-xs font-semibold tabular-nums text-[#9ca3af]">
            <span aria-hidden>{up ? "▲" : s.change_12m < 0 ? "▼" : "■"} </span>
            {signed(s.change_12m, 2)} pts vs a year ago
          </span>
        )}
      </div>
      <Sparkline values={s.history.map((h) => h.value)} label={`${s.label} over the last three years`} />
      <div className="text-[11px] text-[#6b7280]">As of {parseDate(s.latest_date).toLocaleDateString("en-US", { month: "short", year: "numeric" })} · {s.fred_id}</div>
    </div>
  );
}

function MacroTrends({
  macro,
  onMacro,
  effect,
}: {
  macro: MacroInputs;
  onMacro: (next: MacroInputs) => void;
  effect?: MacroEffect;
}) {
  const [data, setData] = useState<MacroData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [refreshing, setRefreshing] = useState(false);

  useEffect(() => {
    const c = new AbortController();
    fetchMacro(false, c.signal).then(setData).catch((e) => !c.signal.aborted && setError(message(e)));
    return () => c.abort();
  }, []);

  const refresh = async () => {
    setRefreshing(true);
    try {
      setData(await fetchMacro(true));
      setError(null);
    } catch (e) {
      setError(message(e));
    } finally {
      setRefreshing(false);
    }
  };

  const ratesChart = useMemo(() => {
    if (!data) return null;
    const wanted = data.series.filter((s) => ["prime", "fed_funds", "treasury_10y"].includes(s.key));
    if (wanted.length === 0) return null;
    const monthOf = (d: string) => d.slice(0, 7);
    const maps = wanted.map((s) => new Map(s.history.map((h) => [monthOf(h.date), h.value])));
    const common = [...maps[0].keys()].filter((k) => maps.every((m) => m.has(k)));
    if (common.length < 2) return null;
    const colors = [COLORS.red, COLORS.blue, COLORS.amber];
    return {
      labels: common.map((k) => parseDate(`${k}-01`).toLocaleDateString("en-US", { month: "short", year: "2-digit" })),
      series: wanted.map((s, i) => ({ name: s.label, color: colors[i % colors.length], values: common.map((k) => maps[i].get(k) as number) })),
    };
  }, [data]);

  const set = (patch: Partial<MacroInputs>) => onMacro({ ...macro, ...patch });
  const status = data ? STATUS[data.status] : null;

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="m-0 text-lg font-semibold">Macro trends: the economy around you</h2>
          <p className="mt-1 text-sm text-[#9ca3af]">Interest rates, inflation, growth and jobs from public data, and how they could move your forecast.</p>
        </div>
        <div className="flex items-center gap-2">
          {status && <Badge tone={status.tone}>{status.text}</Badge>}
          <GhostButton onClick={refresh} disabled={refreshing}>{refreshing ? "Refreshing…" : "Refresh"}</GhostButton>
        </div>
      </div>

      {error && <p role="alert" className="rounded-xl border border-[#7f1d1d] bg-[#2a0f14] px-4 py-3 text-sm text-[#fecaca]">Couldn&apos;t load macro data: {error}</p>}
      {!data && !error && <p className="text-sm text-[#9ca3af]" role="status">Fetching the latest indicators…</p>}

      {data && data.status === "unavailable" && (
        <p role="status" className="rounded-xl border border-[#78350f] bg-[#2b1d07] px-4 py-3 text-sm text-[#fde68a]">
          The live data source couldn&apos;t be reached from the server, so no figures are shown (none are made up). You can still enter the overlay values by hand below.
        </p>
      )}
      {data && data.status === "stale" && (
        <p role="status" className="rounded-xl border border-[#78350f] bg-[#2b1d07] px-4 py-3 text-sm text-[#fde68a]">
          A refresh failed, so these are the last values the server saved{data.fetched_at ? ` (${new Date(data.fetched_at).toLocaleString()})` : ""}.
        </p>
      )}

      {data && data.series.length > 0 && (
        <>
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {data.series.map((s) => <MacroCard key={s.key} s={s} />)}
          </div>
          {ratesChart && (
            <Card title="Benchmark rates">
              <Legend items={ratesChart.series.map((s) => ({ name: s.name, color: s.color }))} />
              <LineChart
                labels={ratesChart.labels}
                series={ratesChart.series}
                axisFormat={(v) => `${v.toFixed(1)}%`}
                valueFormat={(v) => `${v.toFixed(2)}%`}
                includeZero={false}
                ariaLabel="Prime rate, federal funds rate and 10-year Treasury yield over the last three years"
              />
            </Card>
          )}
          <p className="text-xs text-[#6b7280]">Source: {data.source}.</p>
        </>
      )}

      <Card
        title="Apply macro to the forecast"
        right={
          <label className="flex cursor-pointer items-center gap-2 text-sm font-medium text-[#e5e7eb]">
            <input
              type="checkbox"
              checked={macro.apply}
              onChange={(e) => set({ apply: e.target.checked })}
              className="h-4 w-4 accent-[#60a5fa]"
            />
            Overlay on
          </label>
        }
      >
        <p className="mb-3 text-sm text-[#9ca3af]">
          These adjustments sit on top of your assumptions and are off by default. Suggested values compare today&apos;s data with a {data?.norm_pct ?? 2}% norm; change them freely.
        </p>
        <div className="grid gap-4 md:grid-cols-3">
          {MACRO_FIELDS.map((f) => {
            const sug = data?.suggestions[f.key];
            return (
              <div key={f.key}>
                <Field label={`${f.label} (${f.unit})`} hint={f.hint}>
                  <NumInput value={macro[f.key]} min={f.min} max={f.max} suffix={f.unit.startsWith("%") ? "%" : "pts"} ariaLabel={f.label} onChange={(n) => set({ [f.key]: n } as Partial<MacroInputs>)} />
                </Field>
                <div className="mt-1.5 flex items-center justify-between gap-2">
                  <span className="text-[11px] leading-snug text-[#6b7280]">{sug ? sug.basis : "No live suggestion"}</span>
                  {sug && (
                    <GhostButton onClick={() => set({ [f.key]: Math.max(f.min, Math.min(f.max, Math.round(sug.value * 10) / 10)) } as Partial<MacroInputs>)}>
                      Use {signed(sug.value, 1)}
                    </GhostButton>
                  )}
                </div>
              </div>
            );
          })}
        </div>

        <div className="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-2">
          {effect?.applied ? (
            <>
              <Stat label="Effect on ending cash" value={`${effect.ending_cash_impact >= 0 ? "+" : ""}${money(effect.ending_cash_impact)}`} tone={effect.ending_cash_impact >= 0 ? "good" : "bad"} sub="With the overlay vs the same forecast without it" />
              <Stat label="Effect on lowest balance" value={`${effect.lowest_balance_impact >= 0 ? "+" : ""}${money(effect.lowest_balance_impact)}`} tone={effect.lowest_balance_impact >= 0 ? "good" : "bad"} sub="Lowest point of the daily balance, with vs without" />
            </>
          ) : (
            <p className="text-sm text-[#6b7280] sm:col-span-2">
              The overlay is off, so the forecast ignores these values. Turn it on to see their effect on cash.
            </p>
          )}
        </div>
        <p className="mt-3 text-xs leading-snug text-[#6b7280]">
          How it works: rates move loans marked <em>floating</em> (Assumptions → Debt) and new loan or lease capex; inflation compounds on fixed opex lines and salaries; demand growth compounds on new sales. Nothing here is a prediction.
        </p>
      </Card>
    </div>
  );
}

export function TrendsPanel({
  assumptions,
  macroEffect,
  onMacro,
  onApplyMicro,
}: {
  assumptions: Assumptions;
  macroEffect?: MacroEffect;
  onMacro: (next: MacroInputs) => void;
  onApplyMicro: (patch: { growth?: number; dso?: number }) => void;
}) {
  return (
    <div className="space-y-8">
      <MicroTrends assumptions={assumptions} onApply={onApplyMicro} />
      <MacroTrends macro={assumptions.macro} onMacro={onMacro} effect={macroEffect} />
    </div>
  );
}
