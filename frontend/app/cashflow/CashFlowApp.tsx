"use client";

import { useEffect, useMemo, useState } from "react";
import { AssumptionsEditor } from "./AssumptionsEditor";
import { FlowChart, Legend, LineChart } from "./Charts";
import { BalanceSheetPanel } from "./BalanceSheetPanel";
import { CapexPanel } from "./CapexPanel";
import { GlPanel } from "./GlPanel";
import { PayrollPanel } from "./PayrollPanel";
import { KpiCards, ScenarioPanel, StatementTable } from "./Panels";
import { CreditPanel } from "./CreditPanel";
import { ReceivablesTab } from "./ReceivablesTab";
import { TabAssistant } from "./TabAssistant";
import { ProjectionsCard } from "./ProjectionsCard";
import { PayablesPanel } from "./PayablesPanel";
import { TrendsPanel } from "./TrendsPanel";
import { API_BASE, downloadExport, fetchDefaults, fetchForecast, money, shortDate } from "./lib";
import { COLORS, Card } from "./ui";
import {
  NO_ADJUSTMENTS,
  type Adjustments,
  type Assumptions,
  type Defaults,
  type Forecast,
  type Scenario,
  type TabId,
  type View,
} from "./types";

const STORAGE_KEY = "neuraflow.cashflow.assumptions.v1";
const SCENARIO_COLORS: Record<Scenario, string> = {
  base: "#9ca3af",
  best: COLORS.green,
  worst: COLORS.red,
};

function looksLikeAssumptions(value: unknown): value is Assumptions {
  const v = value as Partial<Assumptions> | null;
  return !!v && !!v.general && !!v.sales && !!v.costs && !!v.payroll && !!v.collections && Array.isArray(v.opex) && Array.isArray(v.loans) && Array.isArray(v.one_time);
}

/** Assumptions saved before payables, capex and macro existed lack those sections: fill them in. */
function normalizeAssumptions(saved: Assumptions, defaults: Assumptions): Assumptions {
  const next = structuredClone(saved);
  if (!next.ap) next.ap = structuredClone(defaults.ap);
  // Older saves kept the equipment purchase as a one-time item, so start the capex plan empty.
  if (!next.capex) next.capex = { ...structuredClone(defaults.capex), items: [] };
  if (!next.macro) next.macro = structuredClone(defaults.macro);
  next.loans = next.loans.map((l) => ({ ...l, floating: l.floating ?? false }));
  // Saves from before the payroll roster and balance sheet: adopt the roster and opening asset base.
  if (next.payroll.use_roster === undefined || !Array.isArray(next.payroll.employees)) {
    const d = defaults.payroll;
    next.payroll = {
      ...next.payroll,
      use_roster: d.use_roster,
      employees: structuredClone(d.employees),
      pay_frequency: d.pay_frequency,
      next_pay_date: d.next_pay_date,
      employer_tax_pct: d.employer_tax_pct,
      raise_month: d.raise_month,
      bonus_month: d.bonus_month,
    };
  }
  if (next.capex.opening_ppe_net === undefined) next.capex.opening_ppe_net = defaults.capex.opening_ppe_net;
  return next;
}

const TABS: { id: TabId; label: string }[] = [
  { id: "forecast", label: "Forecast" },
  { id: "receivables", label: "Receivables (AR)" },
  { id: "credit", label: "Credit Score" },
  { id: "payroll", label: "Payroll" },
  { id: "balance", label: "Balance Sheet" },
  { id: "gl", label: "GL & Actuals" },
  { id: "payables", label: "Payables (AP)" },
  { id: "capex", label: "Capex" },
  { id: "trends", label: "Trends" },
];

const message = (e: unknown) => (e instanceof Error ? e.message : "Something went wrong");

export default function CashFlowApp() {
  const [defaults, setDefaults] = useState<Defaults | null>(null);
  const [assumptions, setAssumptions] = useState<Assumptions | null>(null);
  const [scenario, setScenario] = useState<Scenario>("base");
  const [adjustments, setAdjustments] = useState<Adjustments>(NO_ADJUSTMENTS);
  const [focus, setFocus] = useState<{ receivables: string | null; credit: string | null; payables: string | null }>({ receivables: null, credit: null, payables: null });
  // Tabs whose assistant has been opened stay mounted, so each keeps its conversation.
  const [visited, setVisited] = useState<TabId[]>(["forecast"]);
  const [view, setView] = useState<View>("monthly");
  const [tab, setTab] = useState<TabId>("forecast");
  const [forecast, setForecast] = useState<Forecast | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [forecastError, setForecastError] = useState<string | null>(null);
  const [exportError, setExportError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [exporting, setExporting] = useState<"xlsx" | "csv" | null>(null);
  const [attempt, setAttempt] = useState(0);

  // Load data-derived defaults, then restore any assumptions saved in this browser.
  useEffect(() => {
    const controller = new AbortController();
    (async () => {
      try {
        const data = await fetchDefaults(controller.signal);
        let initial = data.assumptions;
        try {
          const saved = window.localStorage.getItem(STORAGE_KEY);
          if (saved) {
            const parsed: unknown = JSON.parse(saved);
            if (looksLikeAssumptions(parsed)) initial = normalizeAssumptions(parsed, data.assumptions);
          }
        } catch {
          /* storage unavailable or corrupt: use defaults */
        }
        setLoadError(null);
        setDefaults(data);
        setAssumptions(initial);
      } catch (e) {
        if (!controller.signal.aborted) setLoadError(message(e));
      }
    })();
    return () => controller.abort();
  }, [attempt]);

  // Re-run the model whenever an input changes (debounced, stale requests cancelled).
  useEffect(() => {
    if (!assumptions) return;
    const controller = new AbortController();
    const timer = setTimeout(async () => {
      setBusy(true);
      try {
        const result = await fetchForecast({ assumptions, scenario, adjustments }, controller.signal);
        setForecast(result);
        setForecastError(null);
      } catch (e) {
        if (!controller.signal.aborted) setForecastError(message(e));
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    }, 250);
    return () => {
      clearTimeout(timer);
      controller.abort();
    };
  }, [assumptions, scenario, adjustments]);

  // Remember assumptions between visits.
  useEffect(() => {
    if (!assumptions) return;
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(assumptions));
    } catch {
      /* ignore */
    }
  }, [assumptions]);

  const periods = useMemo(
    () => (forecast ? (view === "monthly" ? forecast.monthly : forecast.weekly) : []),
    [forecast, view]
  );
  const kpis = forecast ? forecast.kpis[view] : null;

  const balanceChart = useMemo(() => {
    if (!forecast || !assumptions) return null;
    const start = assumptions.general.starting_cash;
    const labels = ["Start", ...periods.map((p) => p.label)];
    const series = (Object.keys(forecast.comparison) as Scenario[]).map((s) => ({
      name: forecast.comparison[s].label,
      color: SCENARIO_COLORS[s],
      dashed: s !== scenario,
      width: s === scenario ? 3 : 1.6,
      values: [start, ...(view === "monthly" ? forecast.comparison[s].monthly_end_cash : forecast.comparison[s].weekly_end_cash)],
    }));
    return { labels, series };
  }, [forecast, assumptions, periods, scenario, view]);

  const flowChart = useMemo(() => {
    const inflows = periods.map((p) => Object.values(p.categories).filter((v) => v > 0).reduce((a, b) => a + b, 0));
    const outflows = periods.map((p) => -Object.values(p.categories).filter((v) => v < 0).reduce((a, b) => a + b, 0));
    return { labels: periods.map((p) => p.label), inflows, outflows, net: periods.map((p) => p.net) };
  }, [periods]);

  const runExport = async (format: "xlsx" | "csv") => {
    if (!assumptions) return;
    setExporting(format);
    setExportError(null);
    try {
      await downloadExport({ assumptions, scenario, adjustments }, format);
    } catch (e) {
      setExportError(message(e));
    } finally {
      setExporting(null);
    }
  };

  const resetAssumptions = () => {
    if (!defaults) return;
    try {
      window.localStorage.removeItem(STORAGE_KEY);
    } catch {
      /* ignore */
    }
    setAssumptions(structuredClone(defaults.assumptions));
  };

  const horizon = assumptions?.general.horizon_months ?? 12;

  return (
    <div className="min-h-screen bg-[#0b0b0f] font-sans text-[#e5e7eb]">
      <div className="mx-auto max-w-[1600px] p-4 sm:p-6">
        <header className="mb-5 flex flex-wrap items-start justify-between gap-4">
          <div>
            <h1 className="text-3xl font-bold tracking-tight">Cash Flow Model</h1>
            <p className="mt-1 text-sm text-[#9ca3af]">
              Operating forecast built from your receivables, costs, payroll and debt.
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            {busy && forecast && <span className="text-xs text-[#9ca3af]" role="status">Updating…</span>}
            <button
              type="button"
              onClick={() => runExport("xlsx")}
              disabled={!forecast || exporting !== null}
              className="rounded-xl border border-[#2563eb] bg-[#1d4ed8] px-4 py-2 text-sm font-semibold text-white transition-colors hover:bg-[#2563eb] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {exporting === "xlsx" ? "Preparing…" : "Download Excel"}
            </button>
            <button
              type="button"
              onClick={() => runExport("csv")}
              disabled={!forecast || exporting !== null}
              className="rounded-xl border border-[#374151] px-4 py-2 text-sm font-semibold text-[#d1d5db] transition-colors hover:bg-[#1f2937] disabled:cursor-not-allowed disabled:opacity-50"
            >
              {exporting === "csv" ? "Preparing…" : "CSV"}
            </button>
          </div>
        </header>

        {exportError && (
          <p role="alert" className="mb-4 rounded-xl border border-[#7f1d1d] bg-[#2a0f14] px-4 py-3 text-sm text-[#fecaca]">
            Export failed: {exportError}
          </p>
        )}

        {loadError && !defaults && (
          <Card title="Can't reach the cash flow API">
            <p className="text-sm text-[#d1d5db]">
              The model runs on the NeuraFlow backend at <code className="rounded bg-[#1f2937] px-1.5 py-0.5">{API_BASE}</code>, which didn&apos;t respond: {loadError}
            </p>
            <p className="mt-2 text-sm text-[#9ca3af]">
              Start it with <code className="rounded bg-[#1f2937] px-1.5 py-0.5">cd backend &amp;&amp; uvicorn main:app --reload</code>, or point the app at a deployed backend with <code className="rounded bg-[#1f2937] px-1.5 py-0.5">NEXT_PUBLIC_API_BASE</code>.
            </p>
            <button
              type="button"
              onClick={() => setAttempt((n) => n + 1)}
              className="mt-3 rounded-lg border border-[#374151] px-3 py-1.5 text-sm font-medium text-[#d1d5db] hover:bg-[#1f2937]"
            >
              Try again
            </button>
          </Card>
        )}

        {!loadError && !defaults && <p className="text-sm text-[#9ca3af]" role="status">Loading your invoice data…</p>}

        {defaults && assumptions && (
          <>
            <div className="mb-5 rounded-xl border border-[#1f2937] bg-[#111216] px-4 py-3 text-xs leading-relaxed text-[#9ca3af]">
              <span className="font-medium text-[#d1d5db]">Data:</span>{" "}
              {defaults.data_summary.invoice_count} invoices · {defaults.data_summary.customer_count} customers · newest invoice {shortDate(defaults.data_summary.last_invoice_date)} · {money(defaults.data_summary.open_ar)} open receivables.{" "}
              <span className="text-[#fbbf24]">{defaults.note}</span>
            </div>

            <div className="grid gap-5 xl:grid-cols-[400px_minmax(0,1fr)]">
              <aside className="space-y-5 xl:sticky xl:top-4 xl:max-h-[calc(100vh-2rem)] xl:self-start xl:overflow-y-auto xl:pr-1">
                <ScenarioPanel
                  scenario={scenario}
                  onScenario={setScenario}
                  adjustments={adjustments}
                  onAdjustments={setAdjustments}
                  presets={defaults.scenarios}
                  comparison={forecast?.comparison}
                  tab={tab}
                  impact={forecast?.whatif_impact}
                />
                <AssumptionsEditor value={assumptions} onChange={setAssumptions} onReset={resetAssumptions} fromGl={defaults.data_summary.driven_by_gl ?? []} />
              </aside>

              <main className={`min-w-0 space-y-5 transition-opacity ${busy ? "opacity-70" : "opacity-100"}`}>
                {forecastError && (
                  <div role="alert" className="rounded-xl border border-[#7f1d1d] bg-[#2a0f14] px-4 py-3 text-sm text-[#fecaca]">
                    <strong className="font-semibold">The model couldn&apos;t run.</strong> {forecastError}
                    <div className="mt-1 text-xs text-[#fca5a5]">Fix the highlighted input, or use “Reset to data defaults”.</div>
                  </div>
                )}

                {!forecast && !forecastError && <p className="text-sm text-[#9ca3af]" role="status">Running the model…</p>}

                <div role="tablist" aria-label="Cash flow sections" className="flex flex-wrap gap-1 rounded-xl bg-[#111216] p-1">
                  {TABS.map((t) => (
                    <button
                      key={t.id}
                      type="button"
                      role="tab"
                      id={`tab-${t.id}`}
                      aria-selected={tab === t.id}
                      aria-controls={`panel-${t.id}`}
                      onClick={() => { setTab(t.id); setVisited((v) => (v.includes(t.id) ? v : [...v, t.id])); }}
                      className={`flex-1 rounded-lg px-3 py-2 text-sm font-semibold transition-colors sm:flex-none ${
                        tab === t.id ? "bg-[#1d4ed8] text-white" : "text-[#9ca3af] hover:bg-[#1f2937] hover:text-[#e5e7eb]"
                      }`}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>

                {tab === "receivables" && forecast && (
                  <div role="tabpanel" id="panel-receivables" aria-labelledby="tab-receivables">
                    <ReceivablesTab
                      forecast={forecast}
                      adjustments={adjustments}
                      calibration={defaults.data_summary.collections_calibration}
                      focus={focus.receivables}
                      onFocus={(id) => setFocus((f) => ({ ...f, receivables: id }))}
                    />
                  </div>
                )}
                {tab === "credit" && (
                  <div role="tabpanel" id="panel-credit" aria-labelledby="tab-credit">
                    <CreditPanel
                      asOf={assumptions.general.as_of}
                      selected={focus.credit}
                      onSelect={(id) => setFocus((f) => ({ ...f, credit: id }))}
                    />
                  </div>
                )}
                {tab === "payroll" && forecast && (
                  <div role="tabpanel" id="panel-payroll" aria-labelledby="tab-payroll">
                    <PayrollPanel forecast={forecast} assumptions={assumptions} />
                  </div>
                )}
                {tab === "balance" && forecast && (
                  <div role="tabpanel" id="panel-balance" aria-labelledby="tab-balance">
                    <BalanceSheetPanel forecast={forecast} />
                  </div>
                )}
                {tab === "gl" && forecast && (
                  <div role="tabpanel" id="panel-gl" aria-labelledby="tab-gl">
                    <GlPanel forecast={forecast} assumptions={assumptions} onAssumptions={setAssumptions} />
                  </div>
                )}
                {tab === "payables" && forecast && (
                  <div role="tabpanel" id="panel-payables" aria-labelledby="tab-payables">
                    <PayablesPanel ap={forecast.ap} assumptions={assumptions} selected={focus.payables} onSelect={(id) => setFocus((f) => ({ ...f, payables: id }))} />
                  </div>
                )}
                {tab === "capex" && forecast && (
                  <div role="tabpanel" id="panel-capex" aria-labelledby="tab-capex">
                    <CapexPanel capex={forecast.capex} horizon={horizon} />
                  </div>
                )}
                {tab === "trends" && (
                  <div role="tabpanel" id="panel-trends" aria-labelledby="tab-trends">
                    <TrendsPanel
                      assumptions={assumptions}
                      macroEffect={forecast?.macro}
                      onMacro={(macro) => setAssumptions({ ...assumptions, macro })}
                      onApplyMicro={(patch) =>
                        setAssumptions({
                          ...assumptions,
                          sales: {
                            ...assumptions.sales,
                            ...(patch.growth !== undefined ? { growth_pct_monthly: patch.growth } : {}),
                            ...(patch.dso !== undefined ? { dso_days: patch.dso } : {}),
                          },
                        })
                      }
                    />
                  </div>
                )}

                {forecast && kpis && tab === "forecast" && (
                  <div role="tabpanel" id="panel-forecast" aria-labelledby="tab-forecast" className="space-y-5">
                    <div className="flex flex-wrap items-center justify-between gap-3">
                      <div className="text-sm text-[#9ca3af]">
                        {forecast.scenario_label} · {shortDate(forecast.as_of)} → {shortDate(view === "monthly" ? forecast.horizon_end : forecast.weekly[forecast.weekly.length - 1].end)}
                      </div>
                      <div role="radiogroup" aria-label="Time view" className="flex gap-1 rounded-xl bg-[#111216] p-1">
                        {(["weekly", "monthly"] as View[]).map((v) => (
                          <button
                            key={v}
                            type="button"
                            role="radio"
                            aria-checked={view === v}
                            onClick={() => setView(v)}
                            className={`rounded-lg px-3 py-1.5 text-sm font-semibold ${view === v ? "bg-[#1d4ed8] text-white" : "text-[#9ca3af] hover:bg-[#1f2937]"}`}
                          >
                            {v === "weekly" ? "13 weeks" : `${horizon} months`}
                          </button>
                        ))}
                      </div>
                    </div>

                    {forecast.alerts.length > 0 && (
                      <div className="space-y-2">
                        {forecast.alerts.map((a, i) => (
                          <p
                            key={i}
                            role={a.level === "danger" ? "alert" : "status"}
                            className={`rounded-xl border px-4 py-3 text-sm ${
                              a.level === "danger"
                                ? "border-[#7f1d1d] bg-[#2a0f14] text-[#fecaca]"
                                : "border-[#78350f] bg-[#2b1d07] text-[#fde68a]"
                            }`}
                          >
                            {a.message}
                          </p>
                        ))}
                      </div>
                    )}

                    <KpiCards
                      kpis={kpis}
                      minCash={assumptions.general.min_cash}
                      arExpected={forecast.ar.expected_in_horizon}
                      arOpen={forecast.ar.open_total}
                      windowLabel={view === "monthly" ? `${horizon} mo` : "13 wk"}
                    />

                    <ProjectionsCard forecast={forecast} minCash={assumptions.general.min_cash} />

                    <div className="grid gap-5 2xl:grid-cols-2">
                      {balanceChart && (
                        <Card title="Cash balance by scenario">
                          <Legend
                            items={[
                              ...balanceChart.series.map((s) => ({ name: s.name, color: s.color, dashed: s.dashed })),
                              { name: "Minimum cash", color: COLORS.amber, dashed: true },
                            ]}
                          />
                          <LineChart
                            labels={balanceChart.labels}
                            series={balanceChart.series}
                            reference={{ value: assumptions.general.min_cash, label: "Minimum" }}
                            ariaLabel={`Projected cash balance across ${periods.length} periods for the base, best and worst cases`}
                          />
                        </Card>
                      )}
                      <Card title="Cash in vs cash out">
                        <Legend
                          items={[
                            { name: "Cash in", color: COLORS.green },
                            { name: "Cash out", color: COLORS.red },
                            { name: "Net", color: COLORS.blue },
                          ]}
                        />
                        <FlowChart
                          {...flowChart}
                          ariaLabel={`Cash in, cash out and net cash flow for each of ${periods.length} periods`}
                        />
                      </Card>
                    </div>

                    <Card title={view === "monthly" ? "Monthly cash flow statement" : "13-week cash flow"}>
                      <StatementTable periods={periods} categories={forecast.categories} minCash={assumptions.general.min_cash} />
                    </Card>

                  </div>
                )}

                {forecast && (
                  <div className="mt-5">
                    {TABS.filter((t) => t.id === tab || visited.includes(t.id)).map((t) => (
                      <div key={t.id} hidden={t.id !== tab}>
                        <TabAssistant
                          tab={t.id}
                          body={{ assumptions, scenario, adjustments }}
                          focus={t.id === "receivables" ? focus.receivables : t.id === "credit" ? focus.credit : t.id === "payables" ? focus.payables : null}
                          onClearFocus={() => setFocus((f) => ({ ...f, ...(t.id === "receivables" ? { receivables: null } : t.id === "credit" ? { credit: null } : { payables: null }) }))}
                          onApply={(changes) => setAdjustments((a) => ({ ...a, ...changes }))}
                        />
                      </div>
                    ))}
                  </div>
                )}
              </main>
            </div>
          </>
        )}
      </div>
    </div>
  );
}
