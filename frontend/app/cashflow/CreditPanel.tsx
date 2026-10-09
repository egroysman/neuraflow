"use client";

import { useEffect, useState } from "react";
import { creditValidationCsvUrl, fetchCredit, fetchCreditValidation, money, shortDate } from "./lib";
import { BAND_STYLE } from "./Panels";
import { Card, Stat } from "./ui";
import type { CreditCustomer, CreditScores, CreditValidation } from "./types";

const pct = (v: number | null | undefined, d = 0) => (v === null || v === undefined ? "n/a" : `${(v * 100).toFixed(d)}%`);

function ScoreBar({ score }: { score: number }) {
  const color = score >= 70 ? "#34d399" : score >= 40 ? "#fbbf24" : "#f87171";
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 w-24 rounded-full bg-[#1f2937]" aria-hidden="true">
        <div className="h-2 rounded-full" style={{ width: `${score}%`, background: color }} />
      </div>
      <span className="w-8 text-right text-sm font-semibold tabular-nums">{score.toFixed(0)}</span>
    </div>
  );
}

function WhyPanel({ c, onClose }: { c: CreditCustomer; onClose: () => void }) {
  return (
    <Card
      title={`Why ${c.customer_id} scores ${c.score.toFixed(0)}`}
      right={
        <button type="button" onClick={onClose} className="text-xs text-[#9ca3af] hover:text-white">
          Close ✕
        </button>
      }
    >
      <ul className="mb-3 list-disc space-y-1 pl-5 text-sm text-[#d1d5db]">
        {c.reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
      <div className="space-y-2">
        {c.components.map((k) => (
          <div key={k.key} className="grid grid-cols-[minmax(0,1fr)_120px_70px] items-center gap-3 text-xs">
            <span className="text-[#d1d5db]">
              {k.label} <span className="text-[#6b7280]">({(k.weight * 100).toFixed(0)}% of score)</span>
            </span>
            <ScoreBar score={k.score} />
            <span />
          </div>
        ))}
      </div>
      <p className="mt-3 text-xs text-[#6b7280]">
        Based on {c.observations} payment{c.observations === 1 ? "" : "s"} and past-due invoices. Confidence: {c.confidence}.
      </p>
    </Card>
  );
}

function Validation({ v, horizon, late }: { v: CreditValidation | null; horizon: number; late: number }) {
  if (!v) return <p className="text-sm text-[#9ca3af]" role="status">Running the back-test…</p>;
  if (!v.available) return <p className="text-sm text-[#9ca3af]">{v.reason}</p>;
  const auc = v.auc.value;
  return (
    <div className="space-y-4" data-testid="validation">
      {v.caveat && (
        <p role="note" className="rounded-xl border border-[#78350f] bg-[#2b1d07] px-4 py-3 text-sm text-[#fde68a]">
          {v.caveat}
        </p>
      )}
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Stat
          label="Ranking accuracy (AUC)"
          value={auc === null ? "n/a" : auc.toFixed(2)}
          sub={v.auc.ci_low !== null && v.auc.ci_high !== null ? `95% range ${v.auc.ci_low.toFixed(2)} to ${v.auc.ci_high.toFixed(2)} · 0.50 is a coin flip` : undefined}
        />
        <Stat label="Invoices tested" value={v.sample.invoices.toLocaleString()} sub={`${v.sample.customers} customers · ${v.data.cutoffs} test dates`} />
        <Stat label="Late in the sample" value={pct(v.sample.base_late_rate)} sub={`${v.sample.late_invoices.toLocaleString()} late invoices`} />
        <Stat
          label="High risk vs Low risk late rate"
          value={`${pct(v.bands.find((b) => b.band === "High risk")?.late_rate)} vs ${pct(v.bands.find((b) => b.band === "Low risk")?.late_rate)}`}
          sub="Share of invoices that ended up late"
        />
      </div>

      <ul className="list-disc space-y-1 pl-5 text-sm text-[#d1d5db]" data-testid="findings">
        {v.findings.map((f) => (
          <li key={f}>{f}</li>
        ))}
      </ul>

      <div className="overflow-x-auto">
        <table className="w-full min-w-[560px] text-sm" data-testid="band-table">
          <caption className="mb-1 text-left text-xs font-medium uppercase tracking-wide text-[#6b7280]">What actually happened, by score band</caption>
          <thead>
            <tr className="text-xs text-[#9ca3af]">
              {["Band", "Invoices", "Customers", "Late rate", "95% range", "vs average"].map((h, i) => (
                <th key={h} scope="col" className={`px-3 py-2 font-medium ${i === 0 ? "text-left" : "text-right"}`}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody className="tabular-nums">
            {v.bands.map((b) => (
              <tr key={b.band} className="border-t border-[#1a1d24]">
                <th scope="row" className="px-3 py-1.5 text-left">
                  <span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${BAND_STYLE[b.band]}`}>{b.band}</span>
                </th>
                <td className="px-3 py-1.5 text-right">{b.invoices.toLocaleString()}</td>
                <td className="px-3 py-1.5 text-right">{b.customers}</td>
                <td className="px-3 py-1.5 text-right font-semibold">{pct(b.late_rate)}</td>
                <td className="px-3 py-1.5 text-right text-[#9ca3af]">{b.ci_low !== null && b.ci_high !== null ? `${pct(b.ci_low)} to ${pct(b.ci_high)}` : "n/a"}</td>
                <td className="px-3 py-1.5 text-right">{b.lift === null ? "n/a" : `${b.lift.toFixed(1)}x`}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="ingredient-table">
            <caption className="mb-1 text-left text-xs font-medium uppercase tracking-wide text-[#6b7280]">What each ingredient adds (AUC alone)</caption>
            <tbody className="tabular-nums">
              {v.components.map((c) => (
                <tr key={c.key} className="border-t border-[#1a1d24]">
                  <th scope="row" className="px-3 py-1.5 text-left font-medium text-[#d1d5db]">
                    {c.label} <span className="text-xs text-[#6b7280]">({(c.weight * 100).toFixed(0)}%)</span>
                  </th>
                  <td className={`px-3 py-1.5 text-right ${c.auc !== null && c.auc < 0.55 ? "text-[#fbbf24]" : ""}`}>{c.auc === null ? "n/a" : c.auc.toFixed(2)}</td>
                </tr>
              ))}
              {v.baselines.map((b) => (
                <tr key={b.name} className="border-t border-[#1a1d24] text-[#9ca3af]">
                  <th scope="row" className="px-3 py-1.5 text-left font-normal">Simple rule: {b.name.toLowerCase()}</th>
                  <td className="px-3 py-1.5 text-right">{b.auc === null ? "n/a" : b.auc.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full text-sm" data-testid="calibration-table">
            <caption className="mb-1 text-left text-xs font-medium uppercase tracking-wide text-[#6b7280]">Five equal groups, riskiest first</caption>
            <thead>
              <tr className="text-xs text-[#9ca3af]">
                <th scope="col" className="px-3 py-1 text-left font-medium">Scores</th>
                <th scope="col" className="px-3 py-1 text-right font-medium">Invoices</th>
                <th scope="col" className="px-3 py-1 text-right font-medium">Late rate</th>
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {v.calibration.map((g) => (
                <tr key={g.group} className="border-t border-[#1a1d24]">
                  <th scope="row" className="px-3 py-1.5 text-left font-normal text-[#d1d5db]">{g.score_low.toFixed(0)} to {g.score_high.toFixed(0)}</th>
                  <td className="px-3 py-1.5 text-right">{g.invoices}</td>
                  <td className="px-3 py-1.5 text-right font-semibold">{pct(g.late_rate)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      <details className="rounded-xl border border-[#1f2937] bg-[#0b0b0f] px-4 py-3 text-sm text-[#d1d5db]">
        <summary className="cursor-pointer font-medium">How this was tested</summary>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-[#9ca3af]">
          {v.method.map((m) => (
            <li key={m}>{m}</li>
          ))}
          <li>
            Test dates run {shortDate(v.data.first_cutoff)} to {shortDate(v.data.last_cutoff)}; outcomes are known through {shortDate(v.data.data_end)}.
            {v.sample.censored_excluded > 0 && ` ${v.sample.censored_excluded} invoices too recent to judge were left out.`}
          </li>
          <li>
            The ingredient weights were set by judgment, then two of them were lowered after this back-test showed they carried little signal. These
            numbers are therefore not fully out-of-sample, and the next test should use data the score has never seen.
          </li>
        </ul>
        <a href={creditValidationCsvUrl(horizon, late)} className="mt-3 inline-block rounded-lg border border-[#374151] px-3 py-1.5 text-xs font-semibold text-[#e5e7eb] hover:border-[#60a5fa]">
          Download every scored invoice (CSV)
        </a>
      </details>
    </div>
  );
}

export function CreditPanel({ asOf, selected, onSelect }: { asOf: string; selected: string | null; onSelect: (id: string | null) => void }) {
  const [scores, setScores] = useState<CreditScores | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ key: string; data: CreditValidation } | null>(null);
  const [horizon, setHorizon] = useState(90);
  const [late, setLate] = useState(10);

  useEffect(() => {
    const controller = new AbortController();
    fetchCredit(asOf, controller.signal)
      .then((d) => {
        setScores(d);
        setError(null);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Could not load scores.");
      });
    return () => controller.abort();
  }, [asOf]);

  useEffect(() => {
    const controller = new AbortController();
    fetchCreditValidation(horizon, late, controller.signal)
      .then((data) => setResult({ key: `${horizon}-${late}`, data }))
      .catch((e) => {
        if (!controller.signal.aborted) setError(e instanceof Error ? e.message : "Could not run the back-test.");
      });
    return () => controller.abort();
  }, [horizon, late]);

  const validation = result && result.key === `${horizon}-${late}` ? result.data : null;

  if (error) return <p role="alert" className="rounded-xl border border-[#7f1d1d] bg-[#2a0f0f] px-4 py-3 text-sm text-[#fca5a5]">{error}</p>;
  if (!scores) return <p className="text-sm text-[#9ca3af]" role="status">Scoring customers…</p>;

  const chosen = scores.customers.find((c) => c.customer_id === selected) ?? null;
  const band = (name: string) => scores.summary.bands.find((b) => b.band === name);

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Stat label="Customers scored" value={scores.summary.customers} sub={`Average score ${scores.summary.average_score?.toFixed(0) ?? "n/a"} · as of ${shortDate(scores.as_of)}`} />
        <Stat label="High risk" value={band("High risk")?.customers ?? 0} tone="bad" sub={`${money(band("High risk")?.open_amount ?? 0)} open · ${band("High risk")?.open_share_pct ?? 0}% of receivables`} />
        <Stat label="Watch" value={band("Watch")?.customers ?? 0} tone="warn" sub={`${money(band("Watch")?.open_amount ?? 0)} open`} />
        <Stat label="Low risk" value={band("Low risk")?.customers ?? 0} tone="good" sub={`${money(band("Low risk")?.open_amount ?? 0)} open`} />
      </div>

      <Card title="Customer payment scores" right={<span className="text-xs text-[#9ca3af]">0 to 100, higher is safer · riskiest first</span>}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[760px] text-sm" data-testid="credit-table">
            <caption className="sr-only">Payment-behavior score for each customer</caption>
            <thead>
              <tr className="bg-[#0b0b0f] text-xs text-[#9ca3af]">
                {["Customer", "Score", "Band", "Confidence", "Avg days late", "Paid late", "Trend", "Open", "Past due"].map((h, i) => (
                  <th key={h} scope="col" className={`whitespace-nowrap px-3 py-2 font-medium ${i < 3 ? "text-left" : "text-right"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="tabular-nums">
              {scores.customers.map((c) => (
                <tr key={c.customer_id} className={`border-t border-[#1a1d24] ${selected === c.customer_id ? "bg-[#12203a]" : ""}`}>
                  <th scope="row" className="px-3 py-1.5 text-left font-medium text-[#e5e7eb]">
                    <button
                      type="button"
                      aria-pressed={selected === c.customer_id}
                      onClick={() => onSelect(selected === c.customer_id ? null : c.customer_id)}
                      className="rounded underline decoration-dotted underline-offset-2 hover:text-white"
                      title="See why, and ask the assistant about this customer"
                    >
                      {c.customer_id}
                    </button>
                  </th>
                  <td className="px-3 py-1.5"><ScoreBar score={c.score} /></td>
                  <td className="px-3 py-1.5"><span className={`rounded-full px-2 py-0.5 text-xs font-semibold ${BAND_STYLE[c.band]}`}>{c.band}</span></td>
                  <td className="px-3 py-1.5 text-right text-[#9ca3af]">{c.confidence}</td>
                  <td className="px-3 py-1.5 text-right">{c.avg_days_late.toFixed(0)}</td>
                  <td className="px-3 py-1.5 text-right">{c.late_rate_pct.toFixed(0)}%</td>
                  <td className={`px-3 py-1.5 text-right ${c.trend_days === null ? "text-[#6b7280]" : c.trend_days > 3 ? "text-[#f87171]" : c.trend_days < -3 ? "text-[#34d399]" : ""}`}>
                    {c.trend_days === null ? "n/a" : `${c.trend_days > 0 ? "+" : ""}${c.trend_days.toFixed(0)} d`}
                  </td>
                  <td className="px-3 py-1.5 text-right">{money(c.open_amount)}</td>
                  <td className="px-3 py-1.5 text-right">{c.past_due_amount > 0 ? money(c.past_due_amount) : "–"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      {chosen && <WhyPanel c={chosen} onClose={() => onSelect(null)} />}

      <Card
        title="Does the score work? Back-test"
        right={
          <div className="flex flex-wrap items-center gap-2 text-xs text-[#9ca3af]">
            <label className="flex items-center gap-1">
              Look ahead
              <select value={horizon} onChange={(e) => setHorizon(Number(e.target.value))} className="rounded border border-[#374151] bg-[#0b0b0f] px-1.5 py-1 text-[#e5e7eb]" aria-label="Look-ahead window in days">
                {[30, 60, 90, 120].map((d) => <option key={d} value={d}>{d} days</option>)}
              </select>
            </label>
            <label className="flex items-center gap-1">
              Late means over
              <select value={late} onChange={(e) => setLate(Number(e.target.value))} className="rounded border border-[#374151] bg-[#0b0b0f] px-1.5 py-1 text-[#e5e7eb]" aria-label="Days past due that count as late">
                {[0, 5, 10, 30].map((d) => <option key={d} value={d}>{d} days</option>)}
              </select>
            </label>
          </div>
        }
      >
        <Validation v={validation} horizon={horizon} late={late} />
      </Card>
    </div>
  );
}
