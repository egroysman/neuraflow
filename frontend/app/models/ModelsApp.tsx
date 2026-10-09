"use client";

import { useEffect, useState } from "react";
import { Card, GhostButton, Stat } from "../cashflow/ui";
import { compact, fetchMlOpenInvoices, fetchMlOverview, money, retrainModels, shortDate } from "../cashflow/lib";
import type { MlMetric, MlModelResult, MlOpenInvoices, MlOverview, MlTask, MlVerdict } from "../cashflow/types";

const VERDICT: Record<MlVerdict, { label: string; cls: string }> = {
  beats: { label: "Beats the simple rule", cls: "border-[#065f46] bg-[#052e22] text-[#6ee7b7]" },
  ties: { label: "No clear difference", cls: "border-[#78350f] bg-[#2b1d07] text-[#fde68a]" },
  worse: { label: "Worse than the simple rule", cls: "border-[#7f1d1d] bg-[#2a0f12] text-[#fca5a5]" },
  unclear: { label: "Too little data to say", cls: "border-[#374151] bg-[#111216] text-[#9ca3af]" },
};

const METRIC_NAME: Record<string, string> = {
  auc: "AUC (higher is better)",
  brier: "Brier score (lower is better)",
  logloss: "Log loss (lower is better)",
  mae: "Average miss, days (lower is better)",
  mape: "Average % miss (lower is better)",
  rmse: "RMSE (lower is better)",
};

function fmtMetric(key: string, m?: MlMetric): string {
  if (!m || m.value === null) return "n/a";
  if (key === "mape") return `${(m.value * 100).toFixed(1)}%`;
  if (key === "mae" && m.value > 1000) return money(m.value);
  return m.value.toFixed(m.value > 100 ? 0 : 3);
}
function fmtCi(key: string, m?: MlMetric): string {
  if (!m?.ci) return "";
  const [a, b] = m.ci;
  return `${fmtMetric(key, { value: a, ci: null })} – ${fmtMetric(key, { value: b, ci: null })}`;
}

function VerdictBadge({ verdict }: { verdict: MlVerdict }) {
  const v = VERDICT[verdict];
  return <span className={`inline-block rounded-full border px-2.5 py-0.5 text-xs font-medium ${v.cls}`}>{v.label}</span>;
}

function MetricTable({ task }: { task: MlTask }) {
  const key = task.validation.primary_metric;
  const keys = Array.from(new Set([...task.models, ...task.baselines].flatMap((r) => Object.keys(r.metrics))));
  const ordered = [key, ...keys.filter((k) => k !== key)];
  const rows: MlModelResult[] = [...task.models, ...task.baselines];
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">Out-of-time accuracy of each model and simple rule for {task.title}</caption>
        <thead>
          <tr className="border-b border-[#1f2937] text-left text-xs text-[#9ca3af]">
            <th scope="col" className="py-2 pr-3 font-medium">Method</th>
            {ordered.map((k) => (
              <th key={k} scope="col" className="px-2 py-2 text-right font-medium">{METRIC_NAME[k] ?? k}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={`${r.is_model}-${r.name}`} className="border-b border-[#1f2937]/60">
              <th scope="row" className="py-2 pr-3 text-left font-normal text-[#e5e7eb]">
                {r.label}
                {r.is_model ? <span className="ml-2 text-[11px] text-[#60a5fa]">model</span> : <span className="ml-2 text-[11px] text-[#6b7280]">{r.primary ? "simple rule · the bar to beat" : "simple rule"}</span>}
              </th>
              {ordered.map((k) => (
                <td key={k} className="px-2 py-2 text-right tabular-nums text-[#e5e7eb]">
                  {fmtMetric(k, r.metrics[k])}
                  {fmtCi(k, r.metrics[k]) && <div className="text-[11px] text-[#6b7280]">{fmtCi(k, r.metrics[k])}</div>}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function TaskCard({ task }: { task: MlTask }) {
  const best = task.models.find((m) => m.name === task.comparison.best_model);
  const imps = best?.importances?.slice(0, 6) ?? [];
  const maxImp = Math.max(0.0001, ...imps.map((i) => Math.abs(i.weight)));
  const shifted = task.drift.filter((d) => d.status !== "stable");
  return (
    <Card title={task.title} right={<VerdictBadge verdict={task.comparison.verdict} />}>
      <p className="mt-0 text-sm text-[#9ca3af]">{task.description}</p>
      <p className="text-xs text-[#6b7280]">
        Feeds: {task.feeds} · {task.data.rows} rows{task.data.first ? ` · ${task.data.first} to ${task.data.last}` : ""} · data fingerprint {task.data.fingerprint} · {task.validation.test_rows} out-of-time tests
      </p>

      <ul className="my-3 space-y-1.5 pl-5 text-sm text-[#e5e7eb]">
        {task.findings.map((f, i) => (
          <li key={i}>{f}</li>
        ))}
      </ul>

      <MetricTable task={task} />
      <p className="mt-2 text-xs text-[#6b7280]">{task.validation.method} Ranges are 95% bootstrap intervals.</p>

      {task.learned_weights && task.learned_weights.length > 0 && (
        <div className="mt-4">
          <h3 className="m-0 mb-2 text-sm font-semibold text-[#e5e7eb]">Credit score ingredient weights: today vs learned</h3>
          <table className="w-full max-w-xl text-sm">
            <thead>
              <tr className="border-b border-[#1f2937] text-left text-xs text-[#9ca3af]">
                <th scope="col" className="py-1.5 font-medium">Ingredient</th>
                <th scope="col" className="py-1.5 text-right font-medium">Today</th>
                <th scope="col" className="py-1.5 text-right font-medium">Learned</th>
              </tr>
            </thead>
            <tbody>
              {task.learned_weights.map((w) => (
                <tr key={w.ingredient} className="border-b border-[#1f2937]/60">
                  <th scope="row" className="py-1.5 text-left font-normal">{w.ingredient}</th>
                  <td className="py-1.5 text-right tabular-nums">{(w.current_weight * 100).toFixed(0)}%</td>
                  <td className="py-1.5 text-right tabular-nums">{(w.learned_weight * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {imps.length > 0 && (
        <div className="mt-4">
          <h3 className="m-0 mb-2 text-sm font-semibold text-[#e5e7eb]">What {best?.label} leans on</h3>
          <ul className="m-0 list-none space-y-1 p-0">
            {imps.map((i) => (
              <li key={i.feature} className="flex items-center gap-2 text-xs text-[#9ca3af]">
                <span className="w-32 shrink-0 truncate sm:w-44" title={i.feature}>{i.feature.replace(/_/g, " ")}</span>
                <span className="h-2 rounded bg-[#2563eb]" style={{ width: `${(Math.abs(i.weight) / maxImp) * 100}%`, maxWidth: "50%" }} aria-hidden />
                <span className="tabular-nums">{i.weight.toFixed(3)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {task.calibration && task.calibration.length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm font-medium text-[#e5e7eb]">Calibration: predicted vs actual late rate</summary>
          <table className="mt-2 w-full max-w-md text-sm">
            <thead>
              <tr className="border-b border-[#1f2937] text-left text-xs text-[#9ca3af]">
                <th scope="col" className="py-1.5 font-medium">Invoices</th>
                <th scope="col" className="py-1.5 text-right font-medium">Predicted</th>
                <th scope="col" className="py-1.5 text-right font-medium">Actual</th>
              </tr>
            </thead>
            <tbody>
              {task.calibration.map((c, i) => (
                <tr key={i} className="border-b border-[#1f2937]/60">
                  <td className="py-1.5">{c.count}</td>
                  <td className="py-1.5 text-right tabular-nums">{(c.predicted * 100).toFixed(0)}%</td>
                  <td className="py-1.5 text-right tabular-nums">{(c.observed * 100).toFixed(0)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </details>
      )}

      <div className="mt-4 text-sm">
        <h3 className="m-0 mb-1 text-sm font-semibold text-[#e5e7eb]">Drift</h3>
        {task.drift.length === 0 ? (
          <p className="m-0 text-xs text-[#6b7280]">Not enough recent data to check for drift.</p>
        ) : shifted.length === 0 ? (
          <p className="m-0 text-xs text-[#6b7280]">Recent inputs look like the training data.</p>
        ) : (
          <p className="m-0 text-xs text-[#fde68a]">
            {shifted.length} of {task.drift.length} inputs look different from the training data lately:{" "}
            {shifted.slice(0, 4).map((d) => `${d.feature.replace(/_/g, " ")} (PSI ${d.psi?.toFixed(2)})`).join(", ")}. Treat predictions with care.
          </p>
        )}
      </div>
    </Card>
  );
}

function OpenInvoices({ data }: { data: MlOpenInvoices }) {
  if (!data.available || !data.invoices || !data.summary) {
    return <p className="text-sm text-[#9ca3af]">{data.reason || "No open invoices to score."}</p>;
  }
  const s = data.summary;
  return (
    <div>
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-3">
        <Stat label="Not-yet-due invoices" value={String(s.invoices)} sub={compact(s.amount)} />
        <Stat label="Expected late (model)" value={compact(s.expected_late_amount)} sub="sum of amount × chance late" />
        <Stat label="Expected late (simple rule)" value={compact(s.simple_rule_late_amount)} sub="customer's average days late" />
      </div>
      <div className="mt-3 overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">Shadow predictions for open invoices that are not yet due</caption>
          <thead>
            <tr className="border-b border-[#1f2937] text-left text-xs text-[#9ca3af]">
              <th scope="col" className="py-2 font-medium">Invoice</th>
              <th scope="col" className="py-2 font-medium">Customer</th>
              <th scope="col" className="py-2 text-right font-medium">Amount</th>
              <th scope="col" className="py-2 text-right font-medium">Due</th>
              <th scope="col" className="py-2 text-right font-medium">Chance late</th>
              <th scope="col" className="py-2 text-right font-medium">Model days late</th>
              <th scope="col" className="py-2 text-right font-medium">Simple-rule days late</th>
            </tr>
          </thead>
          <tbody>
            {data.invoices.map((r) => (
              <tr key={r.invoice_id} className="border-b border-[#1f2937]/60">
                <td className="py-2">{r.invoice_id}</td>
                <td className="py-2">{r.customer_id}</td>
                <td className="py-2 text-right tabular-nums">{money(r.amount)}</td>
                <td className="py-2 text-right tabular-nums">{shortDate(r.due_date)}</td>
                <td className="py-2 text-right tabular-nums">{(r.probability_late * 100).toFixed(0)}%</td>
                <td className="py-2 text-right tabular-nums">{r.expected_days_late.toFixed(0)}</td>
                <td className="py-2 text-right tabular-nums">{r.simple_rule_days_late === null ? "n/a" : r.simple_rule_days_late.toFixed(0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {data.note && <p className="mt-2 text-xs text-[#6b7280]">{data.note}</p>}
    </div>
  );
}

export default function ModelsApp() {
  const [data, setData] = useState<MlOverview | null>(null);
  const [open, setOpen] = useState<MlOpenInvoices | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const ctl = new AbortController();
    Promise.all([fetchMlOverview(ctl.signal), fetchMlOpenInvoices(15, ctl.signal)])
      .then(([o, p]) => {
        setData(o);
        setOpen(p);
      })
      .catch((e: Error) => {
        if (e.name !== "AbortError") setError(e.message || "Could not load the models.");
      });
    return () => ctl.abort();
  }, []);

  async function retrain() {
    setBusy(true);
    setError(null);
    try {
      const o = await retrainModels();
      setData(o);
      setOpen(await fetchMlOpenInvoices(15));
    } catch (e) {
      setError((e as Error).message || "Retraining failed.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="mx-auto w-full min-w-0 max-w-[1200px] space-y-5 px-4 py-6 text-[#e5e7eb] sm:px-6">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="m-0 text-2xl font-semibold">Models</h1>
          <p className="mt-1 max-w-2xl text-sm text-[#9ca3af]">
            These models run behind the scenes on your structured data. Each is tested on the future it had not seen and compared with a simple rule. In shadow mode they never change your cash forecast.
          </p>
        </div>
        <GhostButton onClick={retrain} disabled={busy || !data}>{busy ? "Retraining…" : "Retrain all models"}</GhostButton>
      </header>

      {error && (
        <p role="alert" className="rounded-xl border border-[#7f1d1d] bg-[#2a0f12] px-4 py-3 text-sm text-[#fca5a5]">{error}</p>
      )}
      {!data && !error && <p role="status" className="text-sm text-[#9ca3af]">Loading models…</p>}

      {data && (
        <>
          <p role="status" className="rounded-xl border border-[#78350f] bg-[#2b1d07] px-4 py-3 text-sm text-[#fde68a]">
            {data.data.caveat} Data: {data.data.invoices} invoices, {data.data.customers} customers, {data.data.bills} bills, {data.data.ledger_months} ledger months.
          </p>

          <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
            <Stat label="Models tested" value={String(data.summary.tested)} sub="mode: shadow, forecast unchanged" />
            <Stat label="Beat the simple rule" value={String(data.summary.beats)} tone={data.summary.beats > 0 ? "good" : "default"} />
            <Stat label="No clear difference" value={String(data.summary.ties + data.summary.unclear)} sub={`${data.summary.unclear} with too little data`} />
            <Stat label="Worse than the simple rule" value={String(data.summary.worse)} tone={data.summary.worse > 0 ? "warn" : "default"} />
          </div>

          <ul className="m-0 list-disc space-y-1 pl-5 text-sm text-[#9ca3af]">
            {data.principles.map((p, i) => (
              <li key={i}>{p}</li>
            ))}
          </ul>

          {data.tasks.map((t) => (
            <TaskCard key={t.task} task={t} />
          ))}

          <Card title="Shadow predictions: invoices not yet due">
            {open ? <OpenInvoices data={open} /> : <p className="text-sm text-[#9ca3af]">Loading…</p>}
          </Card>

          <Card title="Model registry">
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <caption className="sr-only">Every trained model version and the data it was trained on</caption>
                <thead>
                  <tr className="border-b border-[#1f2937] text-left text-xs text-[#9ca3af]">
                    <th scope="col" className="py-2 font-medium">Model</th>
                    <th scope="col" className="py-2 text-right font-medium">Version</th>
                    <th scope="col" className="py-2 text-right font-medium">Trained</th>
                    <th scope="col" className="py-2 text-right font-medium">Rows</th>
                    <th scope="col" className="py-2 text-right font-medium">Data fingerprint</th>
                  </tr>
                </thead>
                <tbody>
                  {data.registry.map((r) => (
                    <tr key={r.id} className="border-b border-[#1f2937]/60">
                      <td className="py-2">{r.id}</td>
                      <td className="py-2 text-right tabular-nums">v{r.version}</td>
                      <td className="py-2 text-right tabular-nums">{r.trained_at.slice(0, 16).replace("T", " ")}</td>
                      <td className="py-2 text-right tabular-nums">{r.rows}</td>
                      <td className="py-2 text-right font-mono text-xs">{r.data_fingerprint}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        </>
      )}
    </main>
  );
}
