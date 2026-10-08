"use client";

import { Legend, LineChart, StackedBars } from "./Charts";
import { compact, money, shortDate } from "./lib";
import { Badge, Card, Stat } from "./ui";
import type { Assumptions, Forecast } from "./types";

const DEPT_COLORS = ["#60a5fa", "#34d399", "#fbbf24", "#f472b6", "#a78bfa", "#fb923c", "#22d3ee"];
const FREQ: Record<string, string> = { biweekly: "every 2 weeks", semimonthly: "twice a month", monthly: "monthly" };

export function PayrollPanel({ forecast, assumptions }: { forecast: Forecast; assumptions: Assumptions }) {
  const pr = forecast.payroll;
  if (!pr) {
    return (
      <Card title="Payroll">
        <p className="text-sm text-[#d1d5db]">
          Payroll is using the simple headcount model ({assumptions.payroll.headcount} people × {money(assumptions.payroll.avg_salary)}). Switch on{" "}
          <strong>Assumptions → Payroll & hiring → Use employee roster</strong> to model each person, their pay runs, raises and bonuses.
        </p>
      </Card>
    );
  }

  const labels = forecast.pnl.map((p) => p.label);
  const depts = Object.entries(pr.by_department);
  const series = depts.map(([name, values], i) => ({ name, color: DEPT_COLORS[i % DEPT_COLORS.length], values }));
  const avgMonthly = pr.total_cost / Math.max(1, pr.monthly.length);
  const runsInHorizon = pr.runs.length;
  const nextRun = pr.runs[0];
  const timingGap = pr.total_cash - pr.total_cost;
  const statusTone = { active: "good", planned: "blue", terminated: "neutral" } as const;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
        <Stat label="Active employees" value={pr.active_headcount} sub={`${money(pr.annual_base_active)} annual base pay`} />
        <Stat label="Payroll cost, 12-month plan" value={compact(pr.total_cost)} sub={`${money(avgMonthly)} a month incl. taxes, bonuses, benefits`} />
        <Stat
          label="Next pay run"
          value={nextRun ? shortDate(nextRun.date) : "–"}
          sub={nextRun ? `${money(nextRun.total)} · ${FREQ[pr.pay_frequency]}` : undefined}
        />
        <Stat
          label="Cash vs accrued cost"
          value={`${timingGap >= 0 ? "+" : "-"}${compact(Math.abs(timingGap))}`}
          tone={Math.abs(timingGap) > pr.total_cost * 0.03 ? "warn" : "default"}
          sub={`${runsInHorizon} pay runs in the plan; cash follows pay dates, cost accrues by month`}
        />
      </div>

      <div className="grid gap-5 2xl:grid-cols-2">
        <Card title="Payroll cost by department">
          <Legend items={series.map((s) => ({ name: s.name, color: s.color }))} />
          <StackedBars labels={labels} series={series} ariaLabel="Monthly payroll cost by department including taxes, bonuses and benefits" />
          <p className="mt-2 text-xs leading-snug text-[#6b7280]">
            Raises step up in month {assumptions.payroll.raise_month} each year, bonuses land in month {assumptions.payroll.bonus_month}, and new hires and leavers are prorated by days worked.
          </p>
        </Card>
        <Card title="Headcount">
          <LineChart
            labels={labels}
            series={[{ name: "Employees", color: "#60a5fa", values: pr.headcount }]}
            ariaLabel="Employees on payroll at the end of each month"
            axisFormat={(v) => String(Math.round(v))}
            valueFormat={(v) => String(Math.round(v))}
            includeZero={false}
          />
        </Card>
      </div>

      <Card title="Upcoming pay runs">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[480px] text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-[#6b7280]">
                <th className="py-1.5 pr-3 font-medium">Pay date</th>
                <th className="py-1.5 pr-3 text-right font-medium">Employees</th>
                <th className="py-1.5 pr-3 text-right font-medium">Gross wages</th>
                <th className="py-1.5 pr-3 text-right font-medium">Employer tax</th>
                <th className="py-1.5 text-right font-medium">Cash out</th>
              </tr>
            </thead>
            <tbody>
              {pr.runs.slice(0, 8).map((r) => (
                <tr key={r.date} className="border-t border-[#1f2937] tabular-nums">
                  <td className="py-1.5 pr-3 text-[#e5e7eb]">{shortDate(r.date)}</td>
                  <td className="py-1.5 pr-3 text-right">{r.employees}</td>
                  <td className="py-1.5 pr-3 text-right">{money(r.gross)}</td>
                  <td className="py-1.5 pr-3 text-right text-[#9ca3af]">{money(r.employer_tax)}</td>
                  <td className="py-1.5 text-right font-medium text-[#e5e7eb]">{money(r.total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>

      <Card title="Employee roster">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] text-sm">
            <thead>
              <tr className="text-left text-xs uppercase tracking-wide text-[#6b7280]">
                <th className="py-1.5 pr-3 font-medium">ID</th>
                <th className="py-1.5 pr-3 font-medium">Role</th>
                <th className="py-1.5 pr-3 font-medium">Department</th>
                <th className="py-1.5 pr-3 text-right font-medium">Annual base</th>
                <th className="py-1.5 pr-3 font-medium">Hired</th>
                <th className="py-1.5 font-medium">Status</th>
              </tr>
            </thead>
            <tbody>
              {pr.employees.map((e) => (
                <tr key={e.id} className="border-t border-[#1f2937]">
                  <td className="py-1.5 pr-3 text-[#9ca3af]">{e.id}</td>
                  <td className="py-1.5 pr-3 text-[#e5e7eb]">
                    {e.title}
                    {e.pay_type === "hourly" && <span className="ml-1.5 text-xs text-[#6b7280]">hourly</span>}
                  </td>
                  <td className="py-1.5 pr-3 text-[#d1d5db]">{e.department}</td>
                  <td className="py-1.5 pr-3 text-right tabular-nums">{money(e.annual_base)}</td>
                  <td className="py-1.5 pr-3 tabular-nums text-[#9ca3af]">
                    {shortDate(e.hire_date)}
                    {e.term_date && <span className="text-[#6b7280]"> → {shortDate(e.term_date)}</span>}
                  </td>
                  <td className="py-1.5">
                    <Badge tone={statusTone[e.status]}>{e.status}</Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs leading-snug text-[#6b7280]">Edit people, pay and dates under Assumptions → Payroll & hiring. Names are not used, only roles and IDs.</p>
      </Card>
    </div>
  );
}
