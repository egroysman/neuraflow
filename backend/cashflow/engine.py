"""Event-based cash flow engine.

The model first turns the assumptions into a list of dated cash events (one per
collection, payment, payroll run and so on). Weekly and monthly statements, the
cash balance, KPIs and alerts are all derived from that single list, so every
view of the forecast is guaranteed to reconcile.

Periods are rolling: month ``k`` runs from ``as_of + k months`` up to (but not
including) ``as_of + k+1 months`` and week ``i`` from ``as_of + 7i days``.
"""
from __future__ import annotations

import bisect
import calendar
import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from . import ap, ar, balance_sheet, capex, gl as gl_mod, payroll as payroll_mod
from .models import (
    AP,
    Capex,
    CapexItem,
    SCENARIO_LABELS,
    SCENARIO_PRESETS,
    Adjustments,
    Assumptions,
    Collections,
    Costs,
    Employee,
    ForecastRequest,
    General,
    Hire,
    Loan,
    OneTimeItem,
    OpexLine,
    Payroll,
    Sales,
)

WEEKS = 13

# key, label, section
CATEGORIES: List[Tuple[str, str, str]] = [
    ("ar_collections", "Collections: existing receivables", "operating"),
    ("new_sales_collections", "Collections: new sales", "operating"),
    ("ap_open_bills", "Payables: open vendor bills", "operating"),
    ("cogs_vendors", "Vendors & cost of sales: new purchases", "operating"),
    ("payroll", "Payroll & benefits", "operating"),
    ("opex", "Operating expenses", "operating"),
    ("taxes", "Income taxes", "operating"),
    ("other_operating", "Other operating items", "operating"),
    ("capex_investing", "Capex & other investing", "investing"),
    ("debt_service", "Debt service & lease payments", "financing"),
    ("financing_other", "Other financing", "financing"),
]
CATEGORY_KEYS = [c[0] for c in CATEGORIES]
SECTIONS = ["operating", "investing", "financing"]
ONE_TIME_CATEGORY = {
    "operating": "other_operating",
    "investing": "capex_investing",
    "financing": "financing_other",
}


# --------------------------------------------------------------------------- #
# Small helpers
# --------------------------------------------------------------------------- #


def add_months(d: dt.date, months: int) -> dt.date:
    year, month0 = divmod(d.month - 1 + months, 12)
    year += d.year
    month = month0 + 1
    return dt.date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _days(n: float) -> dt.timedelta:
    return dt.timedelta(days=int(round(n)))


def _round_to(value: float, step: float) -> float:
    return round(value / step) * step


@dataclass
class Event:
    date: dt.date
    category: str
    amount: float  # + inflow, - outflow
    label: str = ""


@dataclass
class ModelRun:
    assumptions: Assumptions
    adjustments: Adjustments
    horizon_end: dt.date
    events: List[Event]
    projected_ar: List[Dict[str, Any]]
    pnl: List[Dict[str, Any]]
    monthly: List[Dict[str, Any]]
    weekly: List[Dict[str, Any]]
    kpis_monthly: Dict[str, Any]
    kpis_weekly: Dict[str, Any]
    extras: Dict[str, Any] = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# Event generation
# --------------------------------------------------------------------------- #


def build_events(
    invoices: List[ar.Invoice],
    a: Assumptions,
    adj: Adjustments,
    bills: Optional[List[ap.Bill]] = None,
    extras: Optional[Dict[str, Any]] = None,
) -> Tuple[List[Event], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Turn assumptions into dated cash events.

    ``extras`` is an optional out-parameter that receives the projected vendor
    bills and the capex schedule so callers can report on them.
    """
    g = a.general
    macro = a.macro if a.macro.apply else None
    rate_delta = (macro.rate_change_pts if macro else 0.0) + adj.rate_change_pts
    inflation = macro.cost_inflation_pct if macro else 0.0
    demand = macro.demand_growth_pct if macro else 0.0
    n = g.horizon_months
    as_of = g.as_of
    end = add_months(as_of, n)
    events: List[Event] = []

    def window(k: int) -> Tuple[dt.date, dt.date]:
        return add_months(as_of, k), add_months(as_of, k + 1)

    # 1. Existing receivables ------------------------------------------------
    projected = ar.project_open_invoices(
        invoices, as_of, a.collections, adj.collection_delay_days, adj.extra_bad_debt_pct,
        adj.collectability_change_pts, adj.past_due_delay_days, adj.top_customer_delay_days,
    )
    for item in projected:
        events.append(
            Event(
                item["expected_date"],
                "ar_collections",
                item["expected_amount"],
                f"Invoice {item['invoice_id']} ({item['customer_id']})",
            )
        )

    # 2. New sales, vendors and the rest of the operating plan ---------------
    growth = (a.sales.growth_pct_monthly + adj.growth_change_pct_pts) / 100.0
    if demand:
        growth += (1.0 + demand / 100.0) ** (1.0 / 12.0) - 1.0
    level = 1.0 + adj.revenue_change_pct / 100.0
    bad_debt = min(1.0, max(0.0, (a.sales.bad_debt_pct + adj.extra_bad_debt_pct) / 100.0))
    dso = max(0.0, a.sales.dso_days + adj.collection_delay_days + adj.new_sales_dso_change_days)
    cogs_pct = min(1.0, max(0.0, (a.costs.cogs_pct + adj.cogs_change_pct_pts) / 100.0))
    dpo = max(0.0, a.costs.dpo_days + adj.dpo_change_days)
    opex_factor = 1.0 + adj.opex_change_pct / 100.0
    collection_profile = [(-15, 0.25), (0, 0.50), (15, 0.25)]

    # Vendor payables that already exist at the start date: bill by bill when
    # the bills are available, otherwise a lump spread over the payment cycle.
    projected_bills: List[Dict[str, Any]] = []
    if a.ap.use_open_bills and bills:
        projected_bills = ap.project_open_bills(
            bills, as_of, a.ap.payment_lag_days, a.ap.overdue_catchup_days + adj.bill_catchup_extra_days,
            adj.dpo_change_days, adj.top_vendor_delay_days,
        )
        for item in projected_bills:
            events.append(
                Event(item["expected_date"], "ap_open_bills", -item["open_amount"],
                      f"Bill {item['bill_id']} ({item['vendor_name']})")
            )
    elif a.costs.opening_ap > 0:
        chunks = max(1, min(35, math.ceil(max(7.0, dpo) / 7.0)))
        for i in range(chunks):
            events.append(
                Event(
                    as_of + dt.timedelta(days=3 + 7 * i),
                    "cogs_vendors",
                    -a.costs.opening_ap / chunks,
                    "Opening vendor payables",
                )
            )

    roster_payroll = None
    if a.payroll.use_roster and a.payroll.employees:
        roster_payroll = payroll_mod.build(a, inflation, window, adj)
        for when, amount, label in roster_payroll["events"]:
            events.append(Event(when, "payroll", amount, label))

    loss_factor = 1.0
    if adj.top_customer_loss_pct:
        year_ago = as_of - dt.timedelta(days=365)
        by_customer: Dict[str, float] = {}
        for inv in invoices:
            if year_ago <= inv.invoice_date <= as_of:
                by_customer[inv.customer_id] = by_customer.get(inv.customer_id, 0.0) + inv.amount
        total_sales = sum(by_customer.values())
        if total_sales > 0:
            loss_factor = 1.0 - max(by_customer.values()) / total_sales * adj.top_customer_loss_pct / 100.0

    revenue: List[float] = []
    cogs: List[float] = []
    payroll_cost: List[float] = []
    opex_cost: List[float] = []
    interest_cost: List[float] = [0.0] * n

    for k in range(n):
        start, finish = window(k)
        rev = a.sales.monthly_revenue * level * (1.0 + growth) ** k
        if adj.seasonal_swing_pct:
            rev *= 1.0 + adj.seasonal_swing_pct / 100.0 * math.cos(2.0 * math.pi * (start.month - 12) / 12.0)
        rev *= loss_factor
        revenue.append(rev)
        invoice_date = start + dt.timedelta(days=14)

        for offset, share in collection_profile:
            when = invoice_date + _days(max(0.0, dso + offset))
            events.append(
                Event(when, "new_sales_collections", rev * (1.0 - bad_debt) * share,
                      f"New sales, month {k + 1}")
            )

        cost = rev * cogs_pct
        cogs.append(cost)
        events.append(
            Event(invoice_date + _days(dpo), "cogs_vendors", -cost, f"Vendors, month {k + 1}")
        )

        # Payroll: roster + pay runs, or the simple headcount model.
        if roster_payroll is not None:
            payroll_cost.append(roster_payroll["monthly"][k])
        else:
            heads = a.payroll.headcount + sum(h.count for h in a.payroll.hires if h.month <= k) + (adj.extra_hires if k >= 1 else 0)
            raise_factor = (1.0 + (a.payroll.salary_growth_pct_annual + inflation + adj.raise_change_pct_pts) / 100.0) ** (k / 12.0)
            payroll = (heads * a.payroll.avg_salary * (1.0 + adj.salary_change_pct / 100.0) * raise_factor / 12.0
                       * (1.0 + (a.payroll.burden_pct + adj.employer_tax_change_pts) / 100.0))
            payroll_cost.append(payroll)
            events.append(Event(start + dt.timedelta(days=14), "payroll", -payroll / 2, f"Payroll, month {k + 1}"))
            events.append(Event(finish - dt.timedelta(days=1), "payroll", -payroll / 2, f"Payroll, month {k + 1}"))

        # Operating expense lines.
        month_opex = 0.0
        for line in a.opex:
            last = n - 1 if line.end_month is None else min(line.end_month, n - 1)
            if not (line.start_month <= k <= last):
                continue
            if line.kind == "fixed":
                amount = line.amount * (1.0 + line.growth_pct_monthly / 100.0) ** (k - line.start_month)
                if inflation:
                    amount *= (1.0 + inflation / 100.0) ** (k / 12.0)
            else:
                amount = line.amount / 100.0 * rev
            amount *= opex_factor
            month_opex += amount
            events.append(Event(start + dt.timedelta(days=1), "opex", -amount, line.name))
        opex_cost.append(month_opex)

    # 3. Debt service ---------------------------------------------------------
    for loan_index, loan in enumerate(a.loans):
        balance = loan.balance
        extra = adj.extra_loan_payment if loan_index == 0 else 0.0
        for k in range(n):
            if balance <= 1e-9:
                break
            rate = loan.annual_rate_pct + (rate_delta if loan.floating else 0.0)
            interest = balance * max(0.0, rate) / 100.0 / 12.0
            payment = min(loan.monthly_payment + extra, balance + interest)
            balance -= payment - interest
            interest_cost[k] += interest
            if payment > 0:
                events.append(
                    Event(window(k)[0] + dt.timedelta(days=9), "debt_service", -payment, loan.name)
                )

    # 3b. Capex plan: purchases, financing payments, depreciation ----------------
    plan = capex.build(a, adj, revenue, lambda k: window(k)[0], rate_delta)
    for when, category, amount, label in plan["events"]:
        events.append(Event(when, category, amount, label))
    for k in range(n):
        interest_cost[k] += plan["interest"][k]
    depreciation_cost = plan["depreciation"]

    # 4. Taxes: paid quarterly on positive pre-tax profit ---------------------
    pretax = [
        revenue[k] - cogs[k] - payroll_cost[k] - opex_cost[k] - interest_cost[k] - depreciation_cost[k]
        for k in range(n)
    ]
    rate = max(0.0, g.tax_rate_pct + adj.tax_rate_change_pts) / 100.0
    tax_expense = [0.0] * n
    for q in range(n // 3):
        profit = sum(pretax[3 * q : 3 * q + 3])
        tax = rate * max(0.0, profit)
        tax_expense[3 * q + 2] = tax
        pay_date = add_months(as_of, 3 * q + 3) + dt.timedelta(days=14)
        if tax > 0 and pay_date < end:
            events.append(Event(pay_date, "taxes", -tax, f"Estimated tax, quarter {q + 1}"))

    # 4b. Ledger-style extras: other monthly cash, a one-off item, owner cash ----
    if adj.other_monthly_cash:
        for k in range(n):
            events.append(Event(window(k)[0] + dt.timedelta(days=2), "other_operating", adj.other_monthly_cash, "Other monthly cash (what-if)"))
    if adj.one_time_cash_item and n > 2:
        events.append(Event(window(2)[0] + dt.timedelta(days=10), "other_operating", adj.one_time_cash_item, "One-off cash item (what-if)"))
    if adj.equity_injection:
        events.append(Event(as_of + dt.timedelta(days=1), "financing_other", adj.equity_injection, "Owner cash in/out (what-if)"))

    # 5. One-time items -------------------------------------------------------
    for item in a.one_time:
        if as_of <= item.date < end:
            events.append(Event(item.date, ONE_TIME_CATEGORY[item.category], item.amount, item.name))

    # Accrual view by month, for the P&L tab and exports.
    pnl = []
    for k in range(n):
        start, finish = window(k)
        gross = revenue[k] - cogs[k]
        pnl.append(
            {
                "index": k,
                "label": start.strftime("%b %Y"),
                "start": start,
                "end": finish,
                "revenue": revenue[k],
                "cogs": cogs[k],
                "gross_profit": gross,
                "payroll": payroll_cost[k],
                "opex": opex_cost[k],
                "depreciation": depreciation_cost[k],
                "interest": interest_cost[k],
                "pretax_profit": pretax[k],
            }
        )

    events.sort(key=lambda e: (e.date, e.category))
    if extras is not None:
        extras["projected_bills"] = projected_bills
        extras["capex"] = plan
        extras["tax_expense"] = tax_expense
        extras["payroll"] = payroll_mod.summary(roster_payroll, a, as_of) if roster_payroll else None
    return events, projected, pnl


# --------------------------------------------------------------------------- #
# Roll-ups
# --------------------------------------------------------------------------- #


def month_windows(as_of: dt.date, n: int) -> List[Tuple[dt.date, dt.date]]:
    return [(add_months(as_of, k), add_months(as_of, k + 1)) for k in range(n)]


def week_windows(as_of: dt.date, n: int = WEEKS) -> List[Tuple[dt.date, dt.date]]:
    return [(as_of + dt.timedelta(days=7 * i), as_of + dt.timedelta(days=7 * (i + 1))) for i in range(n)]


def aggregate(
    events: List[Event],
    windows: List[Tuple[dt.date, dt.date]],
    starting_cash: float,
    min_cash: float,
    labeler,
) -> List[Dict[str, Any]]:
    starts = [w[0] for w in windows]
    periods = [
        {
            "index": i,
            "label": labeler(i, start),
            "start": start,
            "end": finish,
            "categories": {key: 0.0 for key in CATEGORY_KEYS},
        }
        for i, (start, finish) in enumerate(windows)
    ]
    for ev in events:
        if ev.date < windows[0][0] or ev.date >= windows[-1][1]:
            continue
        idx = bisect.bisect_right(starts, ev.date) - 1
        periods[idx]["categories"][ev.category] += ev.amount

    cash = starting_cash
    for p in periods:
        for section in SECTIONS:
            p[section] = sum(p["categories"][k] for k, _, s in CATEGORIES if s == section)
        p["net"] = p["operating"] + p["investing"] + p["financing"]
        p["begin_cash"] = cash
        cash += p["net"]
        p["end_cash"] = cash
        p["below_min"] = cash < min_cash
    return periods


def compute_kpis(
    events: List[Event],
    periods: List[Dict[str, Any]],
    starting_cash: float,
    min_cash: float,
) -> Dict[str, Any]:
    window_start, window_end = periods[0]["start"], periods[-1]["end"]
    in_window = [e for e in events if window_start <= e.date < window_end]

    # Walk the cash balance day by day to find the true low point.
    balance = starting_cash
    lowest, lowest_date = balance, window_start
    first_negative: Optional[dt.date] = None
    first_below_min: Optional[dt.date] = balance < min_cash and window_start or None
    by_day: Dict[dt.date, float] = {}
    for e in in_window:
        by_day[e.date] = by_day.get(e.date, 0.0) + e.amount
    for day in sorted(by_day):
        balance += by_day[day]
        if balance < lowest:
            lowest, lowest_date = balance, day
        if balance < 0 and first_negative is None:
            first_negative = day
        if balance < min_cash and first_below_min is None:
            first_below_min = day

    cash_in = sum(e.amount for e in in_window if e.amount > 0)
    cash_out = -sum(e.amount for e in in_window if e.amount < 0)
    span_months = max((window_end - window_start).days / 30.4375, 1e-9)
    ending = periods[-1]["end_cash"]
    net = ending - starting_cash
    runway = None
    if first_negative is not None:
        runway = round((first_negative - window_start).days / 30.4375, 1)
    return {
        "starting_cash": starting_cash,
        "ending_cash": ending,
        "net_cash_flow": net,
        "cash_in": cash_in,
        "cash_out": cash_out,
        "lowest_balance": lowest,
        "lowest_balance_date": lowest_date,
        "first_below_min_date": first_below_min,
        "first_negative_date": first_negative,
        "runway_months": runway,
        "avg_monthly_burn": (-net / span_months) if net < 0 else 0.0,
        "funding_gap": max(0.0, min_cash - lowest),
        "operating_cash_flow": sum(p["operating"] for p in periods),
        "investing_cash_flow": sum(p["investing"] for p in periods),
        "financing_cash_flow": sum(p["financing"] for p in periods),
    }


# --------------------------------------------------------------------------- #
# Running the model
# --------------------------------------------------------------------------- #


def run_model(
    invoices: List[ar.Invoice],
    a: Assumptions,
    adj: Adjustments,
    bills: Optional[List[ap.Bill]] = None,
) -> ModelRun:
    g = a.general
    extras: Dict[str, Any] = {}
    events, projected, pnl = build_events(invoices, a, adj, bills, extras)
    horizon_end = add_months(g.as_of, g.horizon_months)
    start_cash = g.starting_cash + adj.starting_cash_change

    monthly = aggregate(
        events,
        month_windows(g.as_of, g.horizon_months),
        start_cash,
        g.min_cash,
        lambda i, start: start.strftime("%b %Y"),
    )
    weekly = aggregate(
        events,
        week_windows(g.as_of),
        start_cash,
        g.min_cash,
        lambda i, start: f"Wk {i + 1}",
    )
    extras["projections"] = standard_projections(events, g.as_of, horizon_end, start_cash, g.min_cash)
    return ModelRun(
        assumptions=a,
        adjustments=adj,
        horizon_end=horizon_end,
        events=events,
        projected_ar=projected,
        pnl=pnl,
        monthly=monthly,
        weekly=weekly,
        kpis_monthly=compute_kpis(events, monthly, start_cash, g.min_cash),
        kpis_weekly=compute_kpis(events, weekly, start_cash, g.min_cash),
        extras=extras,
    )


PROJECTION_DAYS = [30, 60, 90, 180, 365]
PROJECTION_LABELS = {30: "30 days", 60: "60 days", 90: "90 days", 180: "180 days", 365: "1 year"}


def standard_projections(
    events: List[Event],
    as_of: dt.date,
    horizon_end: dt.date,
    starting_cash: float,
    min_cash: float,
) -> List[Dict[str, Any]]:
    """Cash position at the standard checkpoints: 30, 60, 90, 180 days and 1 year.

    Computed from the same dated events as everything else, so each checkpoint
    agrees with the weekly and monthly views. A checkpoint past the model's
    horizon is flagged ``complete: False`` rather than guessed.
    """
    out: List[Dict[str, Any]] = []
    section_of = {k: s for k, _, s in CATEGORIES}
    for days in PROJECTION_DAYS:
        end = as_of + dt.timedelta(days=days)
        window = [e for e in events if as_of <= e.date < end]
        by_day: Dict[dt.date, float] = {}
        cats = {k: 0.0 for k in CATEGORY_KEYS}
        sections = {s: 0.0 for s in SECTIONS}
        for e in window:
            by_day[e.date] = by_day.get(e.date, 0.0) + e.amount
            cats[e.category] += e.amount
            sections[section_of[e.category]] += e.amount
        balance = starting_cash
        lowest, lowest_date = balance, as_of
        first_negative: Optional[dt.date] = None
        first_below_min: Optional[dt.date] = as_of if balance < min_cash else None
        for day in sorted(by_day):
            balance += by_day[day]
            if balance < lowest:
                lowest, lowest_date = balance, day
            if balance < 0 and first_negative is None:
                first_negative = day
            if balance < min_cash and first_below_min is None:
                first_below_min = day
        cash_in = sum(e.amount for e in window if e.amount > 0)
        cash_out = -sum(e.amount for e in window if e.amount < 0)
        net = balance - starting_cash
        out.append(
            {
                "days": days,
                "label": PROJECTION_LABELS[days],
                "end_date": end,
                "complete": end <= horizon_end,
                "starting_cash": starting_cash,
                "ending_cash": balance,
                "net_cash_flow": net,
                "cash_in": cash_in,
                "cash_out": cash_out,
                "operating": sections["operating"],
                "investing": sections["investing"],
                "financing": sections["financing"],
                "lowest_balance": lowest,
                "lowest_balance_date": lowest_date,
                "first_below_min_date": first_below_min,
                "first_negative_date": first_negative,
                "avg_monthly_burn": (-net / (days / 30.4375)) if net < 0 else 0.0,
                "funding_gap": max(0.0, min_cash - lowest),
                "categories": cats,
            }
        )
    return out


def _money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def build_alerts(run: ModelRun, aging: List[Dict[str, Any]]) -> List[Dict[str, str]]:
    g = run.assumptions.general
    k = run.kpis_monthly
    alerts: List[Dict[str, str]] = []
    if k["first_negative_date"]:
        alerts.append(
            {
                "level": "danger",
                "message": (
                    f"Cash runs out on {k['first_negative_date'].strftime('%b %d, %Y')} "
                    f"({k['runway_months']} months in). Lowest balance {_money(k['lowest_balance'])}."
                ),
            }
        )
    elif k["first_below_min_date"]:
        alerts.append(
            {
                "level": "warning",
                "message": (
                    f"Cash falls below your {_money(g.min_cash)} minimum on "
                    f"{k['first_below_min_date'].strftime('%b %d, %Y')}. "
                    f"Lowest balance {_money(k['lowest_balance'])} on "
                    f"{k['lowest_balance_date'].strftime('%b %d, %Y')}."
                ),
            }
        )
    total_open = sum(row["open_amount"] for row in aging)
    severe = sum(row["open_amount"] for row in aging if row["bucket"] in ("d91_180", "d180_plus"))
    if total_open > 0 and severe / total_open >= 0.25:
        alerts.append(
            {
                "level": "warning",
                "message": (
                    f"{severe / total_open:.0%} of open receivables ({_money(severe)}) is more than "
                    "90 days past due, so collections are haircut heavily."
                ),
            }
        )
    return alerts


# --------------------------------------------------------------------------- #
# Public entry points
# --------------------------------------------------------------------------- #


def forecast(
    rows: List[Dict[str, Any]],
    req: ForecastRequest,
    bill_rows: Optional[List[Dict[str, Any]]] = None,
    gl_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    invoices = ar.parse_invoices(rows)
    bills = ap.parse_bills(bill_rows) if bill_rows else []
    a = req.assumptions
    total_adj = SCENARIO_PRESETS[req.scenario].plus(req.adjustments)
    run = run_model(invoices, a, total_adj, bills)

    comparison: Dict[str, Any] = {}
    for name, preset in SCENARIO_PRESETS.items():
        other = run if name == req.scenario else run_model(invoices, a, preset.plus(req.adjustments), bills)
        comparison[name] = {
            "label": SCENARIO_LABELS[name],
            "monthly_end_cash": [p["end_cash"] for p in other.monthly],
            "weekly_end_cash": [p["end_cash"] for p in other.weekly],
            "ending_cash": other.kpis_monthly["ending_cash"],
            "lowest_balance": other.kpis_monthly["lowest_balance"],
            "first_negative_date": other.kpis_monthly["first_negative_date"],
            "projection_end_cash": [p["ending_cash"] for p in other.extras["projections"]],
            "projection_lowest": [p["lowest_balance"] for p in other.extras["projections"]],
        }

    g = a.general
    aging = ar.aging_summary(run.projected_ar)
    horizon_end = run.horizon_end
    open_total = sum(p["open_amount"] for p in run.projected_ar)
    expected_total = sum(p["expected_amount"] for p in run.projected_ar)
    expected_in_horizon = sum(
        p["expected_amount"] for p in run.projected_ar if p["expected_date"] < horizon_end
    )
    result = {
        "scenario": req.scenario,
        "scenario_label": SCENARIO_LABELS[req.scenario],
        "effective_adjustments": total_adj.model_dump(),
        "as_of": g.as_of,
        "horizon_end": horizon_end,
        "categories": [{"key": k, "label": label, "section": s} for k, label, s in CATEGORIES],
        "monthly": run.monthly,
        "weekly": run.weekly,
        "pnl": run.pnl,
        "kpis": {"monthly": run.kpis_monthly, "weekly": run.kpis_weekly},
        "projections": run.extras["projections"],
        "alerts": build_alerts(run, aging),
        "comparison": comparison,
        "ap": ap.summarize_ap(
            bills, run.extras.get("projected_bills", []), g.as_of, horizon_end
        )
        | {
            "using_bills": bool(run.extras.get("projected_bills")),
            "opening_ap_lump": a.costs.opening_ap,
        },
        "capex": run.extras["capex"],
        "whatif_impact": whatif_impact(invoices, a, total_adj, bills, run),
        "payroll": run.extras.get("payroll"),
        "balance_sheet": balance_sheet.build(run),
        "gl": gl_mod.compare(gl_mod.prepare(gl_data), g.as_of, run.pnl) if gl_data else None,
        "macro": macro_effect(invoices, a, total_adj, bills, run),
        "ar": {
            "open_total": open_total,
            "expected_total": expected_total,
            "expected_in_horizon": expected_in_horizon,
            "expected_haircut": open_total - expected_total,
            "aging": aging,
            "customers": ar.summarize_customers(
                run.projected_ar, invoices, g.as_of, horizon_end
            ),
        },
    }
    return result


def whatif_impact(invoices, a, adj, bills, run) -> Dict[str, Any]:
    """Cash effect of each group of what-if sliders: the same model with that group switched off."""
    out: Dict[str, Any] = {}
    base_end, base_low = run.kpis_monthly["ending_cash"], run.kpis_monthly["lowest_balance"]
    for group, fields in Adjustments.GROUPS.items():
        if not any(getattr(adj, f) for f in fields):
            out[group] = {"active": False, "ending_cash_impact": 0.0, "lowest_balance_impact": 0.0}
            continue
        other = run_model(invoices, a, adj.without(group), bills)
        out[group] = {
            "active": True,
            "ending_cash_impact": base_end - other.kpis_monthly["ending_cash"],
            "lowest_balance_impact": base_low - other.kpis_monthly["lowest_balance"],
        }
    return out


def macro_effect(
    invoices: List[ar.Invoice],
    a: Assumptions,
    adj: Adjustments,
    bills: List[ap.Bill],
    run: ModelRun,
) -> Dict[str, Any]:
    """What the macro overlay does to cash: the same model with it switched off."""
    m = a.macro
    result: Dict[str, Any] = {
        "applied": bool(m.apply),
        "rate_change_pts": m.rate_change_pts,
        "cost_inflation_pct": m.cost_inflation_pct,
        "demand_growth_pct": m.demand_growth_pct,
        "ending_cash_impact": 0.0,
        "lowest_balance_impact": 0.0,
    }
    if m.apply and (m.rate_change_pts or m.cost_inflation_pct or m.demand_growth_pct):
        off = a.model_copy(deep=True)
        off.macro.apply = False
        base = run_model(invoices, off, adj, bills)
        result["ending_cash_impact"] = run.kpis_monthly["ending_cash"] - base.kpis_monthly["ending_cash"]
        result["lowest_balance_impact"] = run.kpis_monthly["lowest_balance"] - base.kpis_monthly["lowest_balance"]
    return result


def default_assumptions(
    rows: List[Dict[str, Any]],
    today: Optional[dt.date] = None,
    bill_rows: Optional[List[Dict[str, Any]]] = None,
    payroll_rows: Optional[List[Dict[str, Any]]] = None,
    gl_data: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Defaults derived from the invoice data (and the GL and payroll roster, when given).

    Receivables inputs (start date, revenue run-rate, days-to-pay) come from the
    data. Everything else (payroll, opex, debt, one-offs) is an *illustrative
    placeholder* scaled to the revenue run-rate so the model is usable out of
    the box; the UI flags these as needing the user's real numbers.
    """
    summary = ar.derive_data_summary(rows)
    collections, calibration = ar.calibrate_collections(ar.parse_invoices(rows))
    summary["collections_calibration"] = calibration
    bills = ap.parse_bills(bill_rows) if bill_rows else []
    today = today or dt.date.today()
    as_of = summary["as_of"] if summary["invoice_count"] else today
    revenue = summary["monthly_revenue"] or 100_000.0
    salary = 90_000.0
    burden = 22.0
    per_head_month = salary * (1 + burden / 100.0) / 12.0
    heads = max(1, round(revenue * 0.316 / per_head_month))
    ap_summary = ap.derive_ap_summary(bills, as_of) if bills else None
    summary["ap"] = ap_summary
    dpo_days = round(ap_summary["actual_dpo_days"]) if ap_summary and ap_summary["actual_dpo_days"] else 30

    # Ledger baselines: trailing three complete months and balances at the start date.
    gl_base = None
    if gl_data:
        prepared = gl_mod.prepare(gl_data)
        gl_base = gl_mod.baselines(prepared, as_of)
    summary["gl_baselines"] = gl_base
    driven: List[str] = []

    roster = None
    if payroll_rows:
        employees = []
        for r in payroll_rows:
            try:
                employees.append(
                    Employee(
                        id=r["EmployeeID"], department=r.get("Department") or "General", title=r.get("Title") or "",
                        pay_type=(r.get("PayType") or "salary").lower(),
                        annual_salary=float(r.get("AnnualSalary") or 0), hourly_rate=float(r.get("HourlyRate") or 0),
                        hours_per_week=float(r.get("HoursPerWeek") or 40),
                        hire_date=dt.date.fromisoformat(r["HireDate"][:10]),
                        term_date=dt.date.fromisoformat(r["TermDate"][:10]) if r.get("TermDate") else None,
                        bonus_pct=float(r.get("BonusPct") or 0), benefits_monthly=float(r.get("BenefitsMonthly") or 0),
                    )
                )
            except (KeyError, ValueError):
                continue
        if employees:
            nxt = as_of + dt.timedelta(days=(4 - as_of.weekday()) % 7 or 7)
            roster = dict(use_roster=True, employees=employees, pay_frequency="biweekly", next_pay_date=nxt)
            summary["payroll"] = {"employees": len(employees), "source": "roster"}

    if gl_base:
        revenue = gl_base["monthly_revenue"] or revenue
        driven += ["starting_cash", "monthly_revenue", "cogs_pct", "opening_ppe_net"]

    opex_lines = [
        OpexLine(name="Rent & facilities", kind="fixed", amount=_round_to(revenue * 0.052, 500)),
        OpexLine(name="Software & tools", kind="fixed", amount=_round_to(revenue * 0.026, 500)),
        OpexLine(name="Insurance & professional fees", kind="fixed", amount=_round_to(revenue * 0.049, 500)),
        OpexLine(name="Marketing", kind="pct_revenue", amount=4),
    ]
    loan_default = Loan(
        name="Term loan", balance=_round_to(revenue * 1.2, 1000), annual_rate_pct=8,
        monthly_payment=_round_to(revenue * 0.026, 100),
    )
    existing_dep = _round_to(revenue * 0.012, 100)
    if gl_base:
        opex_lines = []
        for name, amount in gl_base["opex_monthly"].items():
            if name == "Marketing" and revenue:
                opex_lines.append(OpexLine(name=name, kind="pct_revenue", amount=round(amount / revenue * 100.0, 2)))
            else:
                opex_lines.append(OpexLine(name=name, kind="fixed", amount=_round_to(amount, 50)))
        driven.append("opex")
        if gl_base["loan"]:
            ln = gl_base["loan"]
            loan_default = Loan(name="Term loan", balance=round(ln["balance"]), annual_rate_pct=round(ln["annual_rate_pct"], 2),
                                monthly_payment=round(ln["monthly_payment"]))
            driven.append("loans")
        existing_dep = round(gl_base["depreciation_monthly"])
        driven.append("depreciation")
    summary["driven_by_gl"] = driven

    assumptions = Assumptions(
        general=General(
            as_of=as_of,
            horizon_months=12,
            starting_cash=round(gl_base["starting_cash"]) if gl_base else _round_to(revenue * 1.5, 1000),
            min_cash=_round_to(revenue * 0.5, 1000),
            tax_rate_pct=25,
        ),
        sales=Sales(
            monthly_revenue=round(revenue),
            growth_pct_monthly=0.5,
            dso_days=round(summary["dso_days"]),
            bad_debt_pct=1,
        ),
        costs=Costs(
            cogs_pct=round(gl_base["cogs_pct"], 1) if gl_base else 40,
            dpo_days=dpo_days,
            opening_ap=round(ap_summary["open_ap"]) if ap_summary else round(revenue * 0.40 * 30 / 30),
        ),
        ap=AP(
            use_open_bills=bool(bills),
            payment_lag_days=ap_summary["typical_lag_days"] if ap_summary else 0.0,
            overdue_catchup_days=14,
        ),
        payroll=Payroll(
            headcount=heads,
            avg_salary=salary,
            burden_pct=burden,
            salary_growth_pct_annual=3,
            hires=[Hire(month=3, count=1), Hire(month=6, count=1)],
            **(roster or {}),
        ),
        opex=opex_lines,
        loans=[loan_default],
        one_time=[],
        capex=Capex(
            maintenance_pct_revenue=1.0,
            maintenance_life_months=60,
            existing_depreciation_monthly=existing_dep,
            opening_ppe_net=round(gl_base['ppe_net']) if gl_base else 0,
            growth_revenue_link=0.5,
            items=[
                CapexItem(
                    name="Production equipment",
                    category="equipment",
                    date=as_of + dt.timedelta(days=120),
                    amount=_round_to(revenue * 0.17, 1000),
                    kind="growth",
                    funding="loan",
                    down_payment_pct=25,
                    term_months=36,
                    annual_rate_pct=8,
                    useful_life_months=84,
                ),
                CapexItem(
                    name="Equipment refresh",
                    category="equipment",
                    date=as_of + dt.timedelta(days=210),
                    amount=_round_to(revenue * 0.05, 500),
                    kind="maintenance",
                    funding="cash",
                    useful_life_months=48,
                ),
                CapexItem(
                    name="ERP / software platform",
                    category="software",
                    date=as_of + dt.timedelta(days=270),
                    amount=_round_to(revenue * 0.07, 1000),
                    kind="growth",
                    funding="lease",
                    down_payment_pct=10,
                    term_months=24,
                    annual_rate_pct=7,
                    useful_life_months=60,
                ),
            ],
        ),
        collections=collections,
    )
    return {"assumptions": assumptions, "data_summary": summary}
