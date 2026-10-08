"use client";

import { StackedBars } from "./Charts";
import { money, monthLabel, shortDate } from "./lib";
import { Badge, Card, Stat } from "./ui";
import type { ApBucket, ApSummary, Assumptions } from "./types";

const AGING_COLORS: Record<ApBucket, string> = {
  current: "#34d399",
  d1_30: "#fbbf24",
  d31_60: "#fb923c",
  d61_90: "#f87171",
  d90_plus: "#dc2626",
};

export function PayablesPanel({
  ap,
  assumptions,
  selected,
  onSelect,
}: {
  ap: ApSummary;
  assumptions: Assumptions;
  selected?: string | null;
  onSelect?: (vendorId: string | null) => void;
}) {
  const total = ap.aging.reduce((sum, a) => sum + a.open_amount, 0) || 1;
  const modelDpo = assumptions.costs.dpo_days;
  const dueByMonth = ap.due_by_month;

  return (
    <div className="space-y-5">
      {!ap.using_bills && (
        <p role="status" className="rounded-xl border border-[#78350f] bg-[#2b1d07] px-4 py-3 text-sm text-[#fde68a]">
          Open vendor bills are switched off, so the forecast pays a single {money(ap.opening_ap_lump)} lump of opening payables instead.
          Turn them back on under <strong>Assumptions → Payables</strong> to pay the {ap.open_bills || ap.bill_count} bills individually.
        </p>
      )}

      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Stat label="Open vendor bills" value={money(ap.open_total)} sub={`${ap.open_bills} bills · ${ap.vendor_count} vendors in the data`} />
        <Stat
          label="Past due"
          value={money(ap.overdue_total)}
          tone={ap.overdue_pct >= 25 ? "bad" : ap.overdue_pct > 0 ? "warn" : "good"}
          sub={`${ap.overdue_pct.toFixed(1)}% of open payables`}
        />
        <Stat
          label="Days payable (actual)"
          value={ap.actual_dpo_days === null ? "–" : `${ap.actual_dpo_days.toFixed(0)} d`}
          sub={`Bill date → payment · model uses ${modelDpo} d on new purchases`}
        />
        <Stat
          label="Top-3 vendor share"
          value={`${ap.top3_share_pct.toFixed(0)}%`}
          tone={ap.top3_share_pct >= 60 ? "warn" : "default"}
          sub="Concentration of open payables"
        />
      </div>

      <div className="grid gap-5 2xl:grid-cols-2">
        <Card title="Open bills by age">
          <div className="mb-2 flex h-4 w-full overflow-hidden rounded-full bg-[#0b0b0f]" role="img" aria-label="Open vendor bills by days past due">
            {ap.aging.map((a) => (
              <div key={a.bucket} style={{ width: `${(a.open_amount / total) * 100}%`, background: AGING_COLORS[a.bucket] }} title={`${a.label}: ${money(a.open_amount)}`} />
            ))}
          </div>
          <ul className="grid gap-1.5 text-sm">
            {ap.aging.map((a) => (
              <li key={a.bucket} className="flex items-center justify-between gap-3">
                <span className="flex items-center gap-2 text-[#d1d5db]">
                  <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: AGING_COLORS[a.bucket] }} />
                  {a.label}
                </span>
                <span className="tabular-nums text-[#e5e7eb]">
                  {money(a.open_amount)} <span className="text-xs text-[#6b7280]">· {a.bills} {a.bills === 1 ? "bill" : "bills"}</span>
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-3 text-xs leading-snug text-[#6b7280]">
            Each bill is paid on its due date plus your typical lag ({assumptions.ap.payment_lag_days >= 0 ? "+" : ""}
            {assumptions.ap.payment_lag_days} days). Bills already past due are cleared within {assumptions.ap.overdue_catchup_days} days, oldest first.
          </p>
        </Card>

        <Card title="Open bills expected to be paid, by month">
          {dueByMonth.length > 0 ? (
            <StackedBars
              labels={dueByMonth.map((m) => monthLabel(m.month))}
              series={[{ name: "Open bills paid", color: "#60a5fa", values: dueByMonth.map((m) => m.amount) }]}
              ariaLabel="Open vendor bills expected to be paid in each month of the forecast"
            />
          ) : (
            <p className="py-8 text-center text-sm text-[#6b7280]">No open bills fall inside the forecast horizon.</p>
          )}
          <p className="mt-2 text-xs text-[#6b7280]">Only bills that already exist. Vendor payments for new purchases are in the cash flow statement.</p>
        </Card>
      </div>

      <Card title="Vendors with open bills">
        <div className="overflow-x-auto rounded-lg border border-[#1f2937]">
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">Largest vendors by open payables</caption>
            <thead>
              <tr className="bg-[#0b0b0f] text-xs text-[#9ca3af]">
                {["Vendor", "Category", "Open", "Share", "Avg days to pay", "Pays vs due", "Oldest past due"].map((h, i) => (
                  <th key={h} scope="col" className={`whitespace-nowrap px-3 py-2 font-medium ${i < 2 ? "text-left" : "text-right"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ap.vendors.map((v) => (
                <tr key={v.vendor_id} className="border-t border-[#1a1d24]">
                  <th scope="row" className={`px-3 py-1.5 text-left font-medium text-[#e5e7eb] ${selected === v.vendor_id ? "bg-[#12203a]" : ""}`}>
                    {onSelect ? (
                      <button
                        type="button"
                        aria-pressed={selected === v.vendor_id}
                        onClick={() => onSelect(selected === v.vendor_id ? null : v.vendor_id)}
                        className="rounded text-left underline decoration-dotted underline-offset-2 hover:text-white"
                        title="Ask the assistant about this vendor"
                      >
                        {v.vendor_name}
                      </button>
                    ) : (
                      v.vendor_name
                    )}
                  </th>
                  <td className="px-3 py-1.5 text-left text-[#9ca3af]">{v.category}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{money(v.open_amount)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{v.share_pct.toFixed(0)}%</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{v.avg_days_to_pay === null ? "–" : v.avg_days_to_pay.toFixed(0)}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">
                    {v.avg_days_vs_due === null ? "–" : v.avg_days_vs_due > 0.5 ? `${v.avg_days_vs_due.toFixed(0)} d late` : v.avg_days_vs_due < -0.5 ? `${Math.abs(v.avg_days_vs_due).toFixed(0)} d early` : "on time"}
                  </td>
                  <td className="px-3 py-1.5 text-right">
                    {v.oldest_days_past_due > 0 ? <Badge tone={v.oldest_days_past_due > 30 ? "bad" : "warn"}>{v.oldest_days_past_due} d</Badge> : <span className="text-[#6b7280]">Not due</span>}
                  </td>
                </tr>
              ))}
              {ap.vendors.length === 0 && (
                <tr><td colSpan={7} className="px-3 py-4 text-center text-[#6b7280]">No open vendor bills at the forecast start date.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Next payments from open bills">
        <div className="overflow-x-auto rounded-lg border border-[#1f2937]">
          <table className="w-full border-collapse text-sm">
            <caption className="sr-only">Next vendor bill payments in date order</caption>
            <thead>
              <tr className="bg-[#0b0b0f] text-xs text-[#9ca3af]">
                {["Expected pay date", "Vendor", "Category", "Due date", "Status", "Amount"].map((h, i) => (
                  <th key={h} scope="col" className={`whitespace-nowrap px-3 py-2 font-medium ${i < 3 ? "text-left" : "text-right"}`}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {ap.upcoming.map((u) => (
                <tr key={u.bill_id} className="border-t border-[#1a1d24]">
                  <td className="px-3 py-1.5 text-left tabular-nums">{shortDate(u.expected_date)}</td>
                  <th scope="row" className="px-3 py-1.5 text-left font-medium text-[#e5e7eb]">{u.vendor_name}</th>
                  <td className="px-3 py-1.5 text-left text-[#9ca3af]">{u.category}</td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{shortDate(u.due_date)}</td>
                  <td className="px-3 py-1.5 text-right">
                    {u.days_past_due > 0 ? <Badge tone="bad">{u.days_past_due} d past due</Badge> : <Badge tone="good">Not yet due</Badge>}
                  </td>
                  <td className="px-3 py-1.5 text-right tabular-nums">{money(u.open_amount)}</td>
                </tr>
              ))}
              {ap.upcoming.length === 0 && (
                <tr><td colSpan={6} className="px-3 py-4 text-center text-[#6b7280]">Nothing to pay from open bills.</td></tr>
              )}
            </tbody>
          </table>
        </div>
        <p className="mt-2 text-xs text-[#6b7280]">
          Data: sample payables dataset ({ap.bill_count} bills). Replace it with your own bills file to use real vendors.
        </p>
      </Card>
    </div>
  );
}
