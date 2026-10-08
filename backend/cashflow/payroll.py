"""Roster-based payroll: pay runs (cash) and accrued payroll cost (P&L).

Cash goes out on pay runs (biweekly, semimonthly or monthly), bonuses in the
bonus month and benefits at month end. The P&L accrues the same pay evenly by
month, so a month with three biweekly runs shows a cash bump but a flat cost.
Raises step up in the chosen calendar month. New hires and leavers are
prorated by days worked.
"""
from __future__ import annotations

import calendar
import datetime as dt
from typing import Any, Callable, Dict, List, Optional

from .models import Adjustments, Assumptions, Employee, Payroll

PERIODS_PER_YEAR = {"biweekly": 26, "semimonthly": 24, "monthly": 12}


def _overlap_days(e: Employee, lo: dt.date, hi: dt.date) -> int:
    """Days in [lo, hi) the employee is employed (hire and term dates inclusive)."""
    a = max(lo, e.hire_date)
    b = hi if e.term_date is None else min(hi, e.term_date + dt.timedelta(days=1))
    return max(0, (b - a).days)


def _raise_factor(as_of: dt.date, when: dt.date, raise_month: int, pct: float) -> float:
    """Number of raise dates (1st of raise_month) in (as_of, when], compounded."""
    steps, y = 0, as_of.year
    while y <= when.year:
        d = dt.date(y, raise_month, 1)
        if as_of < d <= when:
            steps += 1
        y += 1
    return (1.0 + pct / 100.0) ** steps


def _month_end(d: dt.date) -> dt.date:
    return dt.date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def pay_dates(p: Payroll, as_of: dt.date, end: dt.date) -> List[dt.date]:
    out: List[dt.date] = []
    if p.pay_frequency == "biweekly":
        d = p.next_pay_date or as_of
        while d < as_of:
            d += dt.timedelta(days=14)
        while d < end:
            out.append(d)
            d += dt.timedelta(days=14)
        return out
    d = dt.date(as_of.year, as_of.month, 1)
    while d < end:
        cands = [dt.date(d.year, d.month, 15), _month_end(d)] if p.pay_frequency == "semimonthly" else [_month_end(d)]
        out += [c for c in cands if as_of <= c < end]
        d = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def build(
    a: Assumptions,
    inflation_pct: float,
    window: Callable[[int], tuple],
    adj: Optional[Adjustments] = None,
) -> Dict[str, Any]:
    p, g = a.payroll, a.general
    adj = adj or Adjustments()
    pay_scale = 1.0 + adj.salary_change_pct / 100.0
    bonus_scale = max(0.0, 1.0 + adj.bonus_change_pct / 100.0)
    ben_scale = max(0.0, 1.0 + adj.benefits_change_pct / 100.0)
    emps = list(p.employees)
    if adj.extra_hires:
        active = [e for e in emps if e.term_date is None and e.hire_date <= g.as_of]
        avg_base = sum(e.annual_base() for e in active) / len(active) if active else 70000.0
        avg_ben = sum(e.benefits_monthly for e in active) / len(active) if active else 500.0
        for i in range(adj.extra_hires):
            emps.append(Employee(id=f"WI{i + 1:02d}", department="What-if hires", title="Added hire", annual_salary=avg_base,
                                 hire_date=g.as_of + dt.timedelta(days=30), benefits_monthly=avg_ben))
    n, as_of = g.horizon_months, g.as_of
    end = window(n - 1)[1]
    tax = max(0.0, p.employer_tax_pct + adj.employer_tax_change_pts) / 100.0
    raise_pct = p.salary_growth_pct_annual + inflation_pct + adj.raise_change_pct_pts
    per_year = PERIODS_PER_YEAR[p.pay_frequency]
    events: List[tuple] = []
    runs: List[Dict[str, Any]] = []

    # --- cash: pay runs ------------------------------------------------------
    dates = pay_dates(p, as_of, end)
    opening_accrued = 0.0
    for d in dates:
        if p.pay_frequency == "biweekly":
            lo = d - dt.timedelta(days=14)
        elif p.pay_frequency == "semimonthly":
            lo = dt.date(d.year, d.month, 1) if d.day == 15 else dt.date(d.year, d.month, 16)
        else:
            lo = dt.date(d.year, d.month, 1)
        hi = d + dt.timedelta(days=1)
        span = (hi - lo).days
        gross = 0.0
        heads = 0
        if not runs and not events and lo < as_of:
            # first run pays work already done before the start date: that is owed at day 0
            for e in emps:
                done = _overlap_days(e, lo, as_of)
                if done > 0:
                    opening_accrued += e.annual_base() * pay_scale / per_year * (done / span) * (1.0 + tax)
        for e in emps:
            days = _overlap_days(e, lo, hi)
            if days <= 0:
                continue
            heads += 1
            gross += e.annual_base() * pay_scale / per_year * (days / span) * _raise_factor(as_of, d, p.raise_month, raise_pct)
        if gross > 0:
            total = gross * (1.0 + tax)
            events.append((d, -total, f"Payroll run ({heads} paid)"))
            runs.append({"date": d, "gross": gross, "employer_tax": gross * tax, "total": total, "employees": heads})

    # --- monthly accrual, bonuses, benefits ---------------------------------
    monthly: List[float] = []
    benefits_total: List[float] = []
    bonus_total: List[float] = []
    headcount: List[int] = []
    dept_names = sorted({e.department for e in emps})
    by_dept: Dict[str, List[float]] = {k: [0.0] * n for k in dept_names}
    for k in range(n):
        lo, hi = window(k)
        span = (hi - lo).days
        wages = bonus = ben = 0.0
        for e in emps:
            days = _overlap_days(e, lo, hi)
            if days <= 0:
                continue
            frac = days / span
            f = _raise_factor(as_of, lo, p.raise_month, raise_pct)
            w = e.annual_base() * pay_scale / 12.0 * frac * f
            b = 0.0
            if lo.month == p.bonus_month and e.bonus_pct:
                year_ago = lo - dt.timedelta(days=365)
                earned = min(1.0, _overlap_days(e, year_ago, lo) / 365.0) if e.hire_date > year_ago else 1.0
                b = e.annual_base() * pay_scale * f * e.bonus_pct / 100.0 * earned * bonus_scale
            bf = e.benefits_monthly * frac * ben_scale
            wages += w
            bonus += b
            ben += bf
            by_dept[e.department][k] += (w + b) * (1.0 + tax) + bf
        monthly.append((wages + bonus) * (1.0 + tax) + ben)
        benefits_total.append(ben)
        bonus_total.append(bonus)
        headcount.append(sum(1 for e in emps if _overlap_days(e, hi - dt.timedelta(days=1), hi) > 0))
        if bonus > 0:
            pay = dt.date(lo.year, lo.month, 15)
            if pay < lo:
                pay = lo
            events.append((pay, -bonus * (1.0 + tax), "Annual bonuses"))
        if ben > 0:
            events.append((hi - dt.timedelta(days=1), -ben, "Employee benefits"))

    return {
        "events": events,
        "monthly": monthly,
        "bonus": bonus_total,
        "benefits": benefits_total,
        "headcount": headcount,
        "by_department": {k: v for k, v in by_dept.items()},
        "runs": runs,
        "opening_accrued": opening_accrued,
        "pay_frequency": p.pay_frequency,
    }


def summary(result: Dict[str, Any], a: Assumptions, as_of: dt.date) -> Dict[str, Any]:
    """Roster facts for the Payroll tab."""
    p = a.payroll
    emps = []
    for e in p.employees:
        status = "planned" if e.hire_date > as_of else ("terminated" if e.term_date and e.term_date < as_of else "active")
        emps.append({
            "id": e.id, "department": e.department, "title": e.title, "pay_type": e.pay_type,
            "annual_base": e.annual_base(), "hire_date": e.hire_date, "term_date": e.term_date,
            "bonus_pct": e.bonus_pct, "benefits_monthly": e.benefits_monthly, "status": status,
        })
    active = [x for x in emps if x["status"] == "active"]
    return {
        "employees": emps,
        "active_headcount": len(active),
        "annual_base_active": sum(x["annual_base"] for x in active),
        "monthly": result["monthly"],
        "headcount": result["headcount"],
        "by_department": result["by_department"],
        "bonus": result["bonus"],
        "benefits": result["benefits"],
        "runs": result["runs"][:30],
        "pay_frequency": result["pay_frequency"],
        "opening_accrued": result["opening_accrued"],
        "total_cost": sum(result["monthly"]),
        "total_cash": sum(r["total"] for r in result["runs"]) + sum(result["bonus"]) * (1 + p.employer_tax_pct / 100.0) + sum(result["benefits"]),
    }
