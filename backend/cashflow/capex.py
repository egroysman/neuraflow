"""Capital expenditure plan: timing, financing and depreciation.

* **Timing**: each plan item is a dated purchase. Cash items go out in full on
  the purchase date; financed items (loan or lease) pay only the down payment
  then, and an amortising payment each month afterwards. There is no cash
  inflow for the financing itself because the lender pays the vendor directly.
* **Maintenance vs growth**: maintenance capex recurs as a share of revenue
  and is untouched by scenarios beyond following revenue. Growth capex flexes
  with scenario revenue (``growth_revenue_link``) and the capex slider.
* **Depreciation** is straight line over each item's useful life from the
  month of purchase. It is non-cash: it reduces profit (and therefore tax)
  but never the cash balance.
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Callable, Dict, List, Tuple

import calendar

from .models import Adjustments, Assumptions

# (date, category key, amount, label)
CapexEvent = Tuple[dt.date, str, float, str]


def _add_months(d: dt.date, months: int) -> dt.date:
    y, m = divmod(d.month - 1 + months, 12)
    year, month = d.year + y, m + 1
    return dt.date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def pmt(principal: float, annual_rate_pct: float, months: int) -> float:
    """Level monthly payment for an amortising loan."""
    if principal <= 0 or months <= 0:
        return 0.0
    r = annual_rate_pct / 100.0 / 12.0
    if r == 0:
        return principal / months
    return principal * r / (1.0 - (1.0 + r) ** -months)


def growth_scale(a: Assumptions, adj: Adjustments) -> float:
    link = a.capex.growth_revenue_link
    return max(0.0, 1.0 + link * adj.revenue_change_pct / 100.0 + adj.capex_change_pct / 100.0)


def build(
    a: Assumptions,
    adj: Adjustments,
    revenue: List[float],
    month_start: Callable[[int], dt.date],
    rate_delta_pts: float = 0.0,
) -> Dict[str, Any]:
    n = a.general.horizon_months
    as_of = a.general.as_of
    end = month_start(n)
    scale = growth_scale(a, adj)

    def month_index(d: dt.date) -> int:
        for k in range(n):
            if month_start(k) <= d < month_start(k + 1):
                return k
        return -1

    events: List[CapexEvent] = []
    zeros = lambda: [0.0] * n  # noqa: E731
    maint_cash, growth_cash = zeros(), zeros()
    payments, interest, depreciation = zeros(), zeros(), zeros()
    additions = zeros()
    items_out: List[Dict[str, Any]] = []

    # Recurring maintenance capex, a share of revenue, paid mid-month.
    pct = a.capex.maintenance_pct_revenue / 100.0
    life = a.capex.maintenance_life_months
    if pct > 0:
        for k in range(n):
            spend = revenue[k] * pct
            if spend <= 0:
                continue
            maint_cash[k] += spend
            additions[k] += spend
            events.append((month_start(k) + dt.timedelta(days=14), "capex_investing", -spend, "Maintenance capex"))
            for j in range(k, min(n, k + life)):
                depreciation[j] += spend / life

    for item in a.capex.items:
        amount = item.amount * (scale if item.kind == "growth" else 1.0)
        when = item.date
        if item.kind == "growth" and adj.capex_delay_months:
            when = _add_months(item.date, adj.capex_delay_months)
        in_horizon = as_of <= when < end
        row: Dict[str, Any] = {
            "name": item.name,
            "category": item.category,
            "kind": item.kind,
            "funding": item.funding,
            "date": when,
            "planned_date": item.date,
            "amount": amount,
            "planned_amount": item.amount,
            "in_horizon": in_horizon,
            "cash_at_purchase": 0.0,
            "financed": 0.0,
            "monthly_payment": 0.0,
            "payments_in_horizon": 0.0,
            "depreciation_monthly": amount / item.useful_life_months,
            "useful_life_months": item.useful_life_months,
        }
        items_out.append(row)
        if not in_horizon or amount <= 0:
            continue
        k0 = month_index(when)
        financed_share = 0.0 if item.funding == "cash" else 1.0 - item.down_payment_pct / 100.0
        down = amount * (1.0 - financed_share)
        financed = amount * financed_share
        bucket = maint_cash if item.kind == "maintenance" else growth_cash
        bucket[k0] += down
        additions[k0] += amount
        row["cash_at_purchase"] = down
        row["financed"] = financed
        if down > 0:
            events.append((when, "capex_investing", -down, f"{item.name} (capex)"))
        for j in range(k0, min(n, k0 + item.useful_life_months)):
            depreciation[j] += amount / item.useful_life_months

        if financed > 0:
            rate = max(0.0, item.annual_rate_pct + rate_delta_pts)
            payment = pmt(financed, rate, item.term_months)
            row["monthly_payment"] = payment
            balance = financed
            label = f"{item.name} ({'lease' if item.funding == 'lease' else 'loan'} payment)"
            for step in range(1, item.term_months + 1):
                j = k0 + step
                if j >= n:
                    break
                monthly_interest = balance * rate / 100.0 / 12.0
                principal = min(balance, payment - monthly_interest)
                balance -= principal
                interest[j] += monthly_interest
                payments[j] += payment
                row["payments_in_horizon"] += payment
                events.append((month_start(j) + dt.timedelta(days=9), "debt_service", -payment, label))

    existing = a.capex.existing_depreciation_monthly
    for k in range(n):
        depreciation[k] += existing

    monthly = []
    cum_adds = cum_dep = 0.0
    for k in range(n):
        cum_adds += additions[k]
        cum_dep += depreciation[k]
        monthly.append(
            {
                "index": k,
                "label": month_start(k).strftime("%b %Y"),
                "maintenance": maint_cash[k],
                "growth": growth_cash[k],
                "cash_capex": maint_cash[k] + growth_cash[k],
                "financed_payments": payments[k],
                "interest": interest[k],
                "additions": additions[k],
                "depreciation": depreciation[k],
                "net_additions_cum": cum_adds - cum_dep,
            }
        )
    totals = {
        "cash_capex": sum(m["cash_capex"] for m in monthly),
        "maintenance": sum(maint_cash),
        "growth": sum(growth_cash),
        "financed_payments": sum(payments),
        "interest": sum(interest),
        "depreciation": sum(depreciation),
        "total_additions": sum(additions),
        "financed_amount": sum(r["financed"] for r in items_out if r["in_horizon"]),
        "growth_scale": scale,
    }
    return {
        "events": events,
        "interest": interest,
        "depreciation": depreciation,
        "monthly": monthly,
        "items": items_out,
        "totals": totals,
    }
