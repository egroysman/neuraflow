"use client";

import type { ReactNode } from "react";
import { Card, Disclosure, Field, GhostButton, NumInput, inputClass } from "./ui";
import type { Assumptions, Bucket, OneTimeItem, OpexLine } from "./types";

const BUCKET_LABELS: Record<Bucket, string> = {
  current: "Not yet due",
  d1_30: "1–30 days past due",
  d31_60: "31–60 days past due",
  d61_90: "61–90 days past due",
  d91_180: "91–180 days past due",
  d180_plus: "180+ days past due",
};
const BUCKETS = Object.keys(BUCKET_LABELS) as Bucket[];

function Mini({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div>
      <div className="mb-0.5 text-[10px] font-medium uppercase tracking-wide text-[#6b7280]">{label}</div>
      {children}
    </div>
  );
}

function Row({ children, onRemove, name }: { children: ReactNode; onRemove: () => void; name: string }) {
  return (
    <div className="rounded-xl border border-[#1f2937] bg-[#0b0b0f] p-2.5">
      {children}
      <div className="mt-2 text-right">
        <GhostButton danger onClick={onRemove} title={`Remove ${name}`}>
          Remove
        </GhostButton>
      </div>
    </div>
  );
}

export function AssumptionsEditor({
  value,
  onChange,
  onReset,
}: {
  value: Assumptions;
  onChange: (next: Assumptions) => void;
  onReset: () => void;
}) {
  const edit = (fn: (draft: Assumptions) => void) => {
    const next = structuredClone(value);
    fn(next);
    onChange(next);
  };
  const { general: g, sales, costs, payroll } = value;

  return (
    <Card
      title="Assumptions"
      right={
        <GhostButton onClick={onReset} title="Replace everything with the defaults derived from your invoice data">
          Reset to data defaults
        </GhostButton>
      }
    >
      <div className="-mt-1">
        <Disclosure title="General" defaultOpen>
          <Field label="Forecast start date" hint="Receivables are measured as of this date.">
            <input
              type="date"
              value={g.as_of}
              onChange={(e) => e.target.value && edit((d) => void (d.general.as_of = e.target.value))}
              className={inputClass}
            />
          </Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Horizon (months)">
              <NumInput value={g.horizon_months} min={3} max={24} onChange={(n) => edit((d) => void (d.general.horizon_months = Math.round(n)))} />
            </Field>
            <Field label="Income tax rate">
              <NumInput value={g.tax_rate_pct} min={0} max={60} suffix="%" onChange={(n) => edit((d) => void (d.general.tax_rate_pct = n))} />
            </Field>
            <Field label="Starting cash">
              <NumInput value={g.starting_cash} prefix="$" onChange={(n) => edit((d) => void (d.general.starting_cash = n))} />
            </Field>
            <Field label="Minimum cash target" hint="Alerts fire below this.">
              <NumInput value={g.min_cash} min={0} prefix="$" onChange={(n) => edit((d) => void (d.general.min_cash = n))} />
            </Field>
          </div>
        </Disclosure>

        <Disclosure title="Sales & collections" badge="from data">
          <div className="grid grid-cols-2 gap-3">
            <Field label="New invoicing / month">
              <NumInput value={sales.monthly_revenue} min={0} prefix="$" onChange={(n) => edit((d) => void (d.sales.monthly_revenue = n))} />
            </Field>
            <Field label="Growth / month">
              <NumInput value={sales.growth_pct_monthly} min={-20} max={30} suffix="%" onChange={(n) => edit((d) => void (d.sales.growth_pct_monthly = n))} />
            </Field>
            <Field label="Days to collect (DSO)">
              <NumInput value={sales.dso_days} min={0} max={240} suffix="days" onChange={(n) => edit((d) => void (d.sales.dso_days = n))} />
            </Field>
            <Field label="Bad debt on new sales">
              <NumInput value={sales.bad_debt_pct} min={0} max={100} suffix="%" onChange={(n) => edit((d) => void (d.sales.bad_debt_pct = n))} />
            </Field>
          </div>
          <div>
            <div className="mb-1 text-xs font-medium text-[#9ca3af]">Existing receivables, by age</div>
            <div className="grid grid-cols-[1fr_74px_74px] items-center gap-x-2 gap-y-1.5 text-xs">
              <span />
              <span className="text-right text-[10px] uppercase tracking-wide text-[#6b7280]">Collect %</span>
              <span className="text-right text-[10px] uppercase tracking-wide text-[#6b7280]">Paid in (d)</span>
              {BUCKETS.map((b) => (
                <div key={b} className="contents">
                  <span className="text-[#d1d5db]">{BUCKET_LABELS[b]}</span>
                  <NumInput ariaLabel={`Collectability ${BUCKET_LABELS[b]}`} value={value.collections.collectability_pct[b]} min={0} max={100} onChange={(n) => edit((d) => void (d.collections.collectability_pct[b] = n))} />
                  <NumInput ariaLabel={`Days to pay ${BUCKET_LABELS[b]}`} value={value.collections.overdue_lag_days[b]} min={0} max={365} onChange={(n) => edit((d) => void (d.collections.overdue_lag_days[b] = n))} />
                </div>
              ))}
            </div>
          </div>
        </Disclosure>

        <Disclosure title="Cost of sales & vendors">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Cost of sales">
              <NumInput value={costs.cogs_pct} min={0} max={100} suffix="% rev" onChange={(n) => edit((d) => void (d.costs.cogs_pct = n))} />
            </Field>
            <Field label="Days to pay vendors">
              <NumInput value={costs.dpo_days} min={0} max={240} suffix="days" onChange={(n) => edit((d) => void (d.costs.dpo_days = n))} />
            </Field>
          </div>
          <Field label="Vendor payables owed at start" hint="Paid down over the first weeks.">
            <NumInput value={costs.opening_ap} min={0} prefix="$" onChange={(n) => edit((d) => void (d.costs.opening_ap = n))} />
          </Field>
        </Disclosure>

        <Disclosure title="Payroll & hiring" badge={`${payroll.headcount} people`}>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Headcount">
              <NumInput value={payroll.headcount} min={0} max={5000} onChange={(n) => edit((d) => void (d.payroll.headcount = Math.round(n)))} />
            </Field>
            <Field label="Avg salary / year">
              <NumInput value={payroll.avg_salary} min={0} prefix="$" onChange={(n) => edit((d) => void (d.payroll.avg_salary = n))} />
            </Field>
            <Field label="Taxes & benefits">
              <NumInput value={payroll.burden_pct} min={0} max={100} suffix="%" onChange={(n) => edit((d) => void (d.payroll.burden_pct = n))} />
            </Field>
            <Field label="Raises / year">
              <NumInput value={payroll.salary_growth_pct_annual} min={-20} max={50} suffix="%" onChange={(n) => edit((d) => void (d.payroll.salary_growth_pct_annual = n))} />
            </Field>
          </div>
          {payroll.hires.map((h, i) => (
            <Row key={i} name={`hire ${i + 1}`} onRemove={() => edit((d) => void d.payroll.hires.splice(i, 1))}>
              <div className="grid grid-cols-2 gap-2">
                <Mini label="Starts in month #">
                  <NumInput ariaLabel={`Hire ${i + 1} start month`} value={h.month} min={0} max={60} onChange={(n) => edit((d) => void (d.payroll.hires[i].month = Math.round(n)))} />
                </Mini>
                <Mini label="New heads">
                  <NumInput ariaLabel={`Hire ${i + 1} head count`} value={h.count} min={1} max={500} onChange={(n) => edit((d) => void (d.payroll.hires[i].count = Math.max(1, Math.round(n))))} />
                </Mini>
              </div>
            </Row>
          ))}
          <GhostButton onClick={() => edit((d) => void d.payroll.hires.push({ month: 1, count: 1 }))}>+ Add hire</GhostButton>
        </Disclosure>

        <Disclosure title="Operating expenses" badge={`${value.opex.length} lines`}>
          {value.opex.map((o, i) => (
            <Row key={i} name={o.name || `expense ${i + 1}`} onRemove={() => edit((d) => void d.opex.splice(i, 1))}>
              <div className="grid grid-cols-[1fr_auto] gap-2">
                <input aria-label={`Expense ${i + 1} name`} value={o.name} maxLength={80} onChange={(e) => edit((d) => void (d.opex[i].name = e.target.value))} className={inputClass} placeholder="Name" />
                <select aria-label={`Expense ${i + 1} type`} value={o.kind} onChange={(e) => edit((d) => void (d.opex[i].kind = e.target.value as OpexLine["kind"]))} className={`${inputClass} w-auto`}>
                  <option value="fixed">$ / month</option>
                  <option value="pct_revenue">% of revenue</option>
                </select>
              </div>
              <div className="mt-2 grid grid-cols-2 gap-2">
                <Mini label={o.kind === "fixed" ? "Amount / month" : "Share of revenue"}>
                  <NumInput ariaLabel={`Expense ${i + 1} amount`} value={o.amount} min={0} prefix={o.kind === "fixed" ? "$" : undefined} suffix={o.kind === "fixed" ? undefined : "%"} onChange={(n) => edit((d) => void (d.opex[i].amount = n))} />
                </Mini>
                <Mini label="Growth / month">
                  <NumInput ariaLabel={`Expense ${i + 1} growth`} value={o.growth_pct_monthly} min={-20} max={20} suffix="%" onChange={(n) => edit((d) => void (d.opex[i].growth_pct_monthly = n))} />
                </Mini>
                <Mini label="Starts month #">
                  <NumInput ariaLabel={`Expense ${i + 1} start month`} value={o.start_month} min={0} max={60} onChange={(n) => edit((d) => void (d.opex[i].start_month = Math.round(n)))} />
                </Mini>
                <Mini label="Ends month # (blank = never)">
                  <input
                    aria-label={`Expense ${i + 1} end month`}
                    inputMode="numeric"
                    value={o.end_month ?? ""}
                    onChange={(e) => {
                      const n = parseInt(e.target.value, 10);
                      edit((d) => void (d.opex[i].end_month = Number.isFinite(n) ? Math.min(60, Math.max(0, n)) : null));
                    }}
                    className={`${inputClass} text-right`}
                  />
                </Mini>
              </div>
            </Row>
          ))}
          <GhostButton onClick={() => edit((d) => void d.opex.push({ name: "New expense", kind: "fixed", amount: 0, growth_pct_monthly: 0, start_month: 0, end_month: null }))}>
            + Add expense
          </GhostButton>
        </Disclosure>

        <Disclosure title="Debt" badge={`${value.loans.length} loans`}>
          {value.loans.map((l, i) => (
            <Row key={i} name={l.name || `loan ${i + 1}`} onRemove={() => edit((d) => void d.loans.splice(i, 1))}>
              <input aria-label={`Loan ${i + 1} name`} value={l.name} maxLength={80} onChange={(e) => edit((d) => void (d.loans[i].name = e.target.value))} className={inputClass} placeholder="Name" />
              <div className="mt-2 grid grid-cols-3 gap-2">
                <Mini label="Balance">
                  <NumInput ariaLabel={`Loan ${i + 1} balance`} value={l.balance} min={0} prefix="$" onChange={(n) => edit((d) => void (d.loans[i].balance = n))} />
                </Mini>
                <Mini label="Rate / yr">
                  <NumInput ariaLabel={`Loan ${i + 1} rate`} value={l.annual_rate_pct} min={0} max={60} suffix="%" onChange={(n) => edit((d) => void (d.loans[i].annual_rate_pct = n))} />
                </Mini>
                <Mini label="Payment / mo">
                  <NumInput ariaLabel={`Loan ${i + 1} payment`} value={l.monthly_payment} min={0} prefix="$" onChange={(n) => edit((d) => void (d.loans[i].monthly_payment = n))} />
                </Mini>
              </div>
            </Row>
          ))}
          <GhostButton onClick={() => edit((d) => void d.loans.push({ name: "New loan", balance: 0, annual_rate_pct: 0, monthly_payment: 0 }))}>+ Add loan</GhostButton>
        </Disclosure>

        <Disclosure title="One-time items" badge={`${value.one_time.length}`}>
          {value.one_time.map((o, i) => (
            <Row key={i} name={o.name || `item ${i + 1}`} onRemove={() => edit((d) => void d.one_time.splice(i, 1))}>
              <input aria-label={`One-time item ${i + 1} name`} value={o.name} maxLength={80} onChange={(e) => edit((d) => void (d.one_time[i].name = e.target.value))} className={inputClass} placeholder="Name" />
              <div className="mt-2 grid grid-cols-2 gap-2">
                <Mini label="Date">
                  <input aria-label={`One-time item ${i + 1} date`} type="date" value={o.date} onChange={(e) => e.target.value && edit((d) => void (d.one_time[i].date = e.target.value))} className={inputClass} />
                </Mini>
                <Mini label="Amount (− out, + in)">
                  <NumInput ariaLabel={`One-time item ${i + 1} amount`} value={o.amount} prefix="$" onChange={(n) => edit((d) => void (d.one_time[i].amount = n))} />
                </Mini>
              </div>
              <div className="mt-2">
                <Mini label="Section">
                  <select aria-label={`One-time item ${i + 1} section`} value={o.category} onChange={(e) => edit((d) => void (d.one_time[i].category = e.target.value as OneTimeItem["category"]))} className={inputClass}>
                    <option value="operating">Operating</option>
                    <option value="investing">Investing (capex)</option>
                    <option value="financing">Financing</option>
                  </select>
                </Mini>
              </div>
            </Row>
          ))}
          <GhostButton onClick={() => edit((d) => void d.one_time.push({ name: "New item", date: d.general.as_of, amount: 0, category: "operating" }))}>+ Add item</GhostButton>
        </Disclosure>
      </div>
    </Card>
  );
}
