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

from . import ar
from .models import (
    SCENARIO_LABELS,
    SCENARIO_PRESETS,
    Adjustments,
    Assumptions,
    Collections,
    Costs,
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
    ("cogs_vendors", "Vendors & cost of sales", "operating"),
    ("payroll", "Payroll & benefits", "operating"),
    ("opex", "Operating expenses", "operating"),
    ("taxes", "Income taxes", "operating"),
    ("other_operating", "Other operating items", "operating"),
    ("capex_investing", "Capex & other investing", "investing"),
    ("debt_service", "Debt service", "financing"),
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
    invoices: List[ar.Invoice], a: Assumptions, adj: Adjustments
) -> Tuple[List[Event], List[Dict[str, Any]], List[Dict[str, Any]]]:
    g = a.general
    n = g.horizon_months
    as_of = g.as_of
    end = add_months(as_of, n)
    events: List[Event] = []

    def window(k: int) -> Tuple[dt.date, dt.date]:
        return add_months(as_of, k), add_months(as_of, k + 1)

    # 1. Existing receivables ------------------------------------------------
    projected = ar.project_open_invoices(
        invoices, as_of, a.collections, adj.collection_delay_days, adj.extra_bad_debt_pct
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
    level = 1.0 + adj.revenue_change_pct / 100.0
    bad_debt = min(1.0, max(0.0, (a.sales.bad_debt_pct + adj.extra_bad_debt_pct) / 100.0))
    dso = max(0.0, a.sales.dso_days + adj.collection_delay_days)
    cogs_pct = min(1.0, max(0.0, (a.costs.cogs_pct + adj.cogs_change_pct_pts) / 100.0))
    dpo = max(0.0, a.costs.dpo_days + adj.dpo_change_days)
    opex_factor = 1.0 + adj.opex_change_pct / 100.0
    collection_profile = [(-15, 0.25), (0, 0.50), (15, 0.25)]

    # Vendor payables that already exist at the start date.
    if a.costs.opening_ap > 0:
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

    revenue: List[float] = []
    cogs: List[float] = []
    payroll_cost: List[float] = []
    opex_cost: List[float] = []
    interest_cost: List[float] = [0.0] * n

    for k in range(n):
        start, finish = window(k)
        rev = a.sales.monthly_revenue * level * (1.0 + growth) ** k
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

        # Payroll: headcount, annual raises, hiring plan; paid twice a month.
        heads = a.payroll.headcount + sum(h.count for h in a.payroll.hires if h.month <= k)
        raise_factor = (1.0 + a.payroll.salary_growth_pct_annual / 100.0) ** (k / 12.0)
        payroll = heads * a.payroll.avg_salary * raise_factor / 12.0 * (1.0 + a.payroll.burden_pct / 100.0)
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
            else:
                amount = line.amount / 100.0 * rev
            amount *= opex_factor
            month_opex += amount
            events.append(Event(start + dt.timedelta(days=1), "opex", -amount, line.name))
        opex_cost.append(month_opex)

    # 3. Debt service ---------------------------------------------------------
    for loan in a.loans:
        balance = loan.balance
        for k in range(n):
            if balance <= 1e-9:
                break
            interest = balance * loan.annual_rate_pct / 100.0 / 12.0
            payment = min(loan.monthly_payment, balance + interest)
            balance -= payment - interest
            interest_cost[k] += interest
            if payment > 0:
                events.append(
                    Event(window(k)[0] + dt.timedelta(days=9), "debt_service", -payment, loan.name)
                )

    # 4. Taxes: paid quarterly on positive pre-tax profit ---------------------
    pretax = [
        revenue[k] - cogs[k] - payroll_cost[k] - opex_cost[k] - interest_cost[k] for k in range(n)
    ]
    rate = g.tax_rate_pct / 100.0
    for q in range(n // 3):
        profit = sum(pretax[3 * q : 3 * q + 3])
        tax = rate * max(0.0, profit)
        pay_date = add_months(as_of, 3 * q + 3) + dt.timedelta(days=14)
        if tax > 0 and pay_date < end:
            events.append(Event(pay_date, "taxes", -tax, f"Estimated tax, quarter {q + 1}"))

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
                "interest": interest_cost[k],
                "pretax_profit": pretax[k],
            }
        )

    events.sort(key=lambda e: (e.date, e.category))
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


def run_model(invoices: List[ar.Invoice], a: Assumptions, adj: Adjustments) -> ModelRun:
    g = a.general
    events, projected, pnl = build_events(invoices, a, adj)
    horizon_end = add_months(g.as_of, g.horizon_months)

    monthly = aggregate(
        events,
        month_windows(g.as_of, g.horizon_months),
        g.starting_cash,
        g.min_cash,
        lambda i, start: start.strftime("%b %Y"),
    )
    weekly = aggregate(
        events,
        week_windows(g.as_of),
        g.starting_cash,
        g.min_cash,
        lambda i, start: f"Wk {i + 1}",
    )
    return ModelRun(
        assumptions=a,
        adjustments=adj,
        horizon_end=horizon_end,
        events=events,
        projected_ar=projected,
        pnl=pnl,
        monthly=monthly,
        weekly=weekly,
        kpis_monthly=compute_kpis(events, monthly, g.starting_cash, g.min_cash),
        kpis_weekly=compute_kpis(events, weekly, g.starting_cash, g.min_cash),
    )


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


def forecast(rows: List[Dict[str, Any]], req: ForecastRequest) -> Dict[str, Any]:
    invoices = ar.parse_invoices(rows)
    a = req.assumptions
    total_adj = SCENARIO_PRESETS[req.scenario].plus(req.adjustments)
    run = run_model(invoices, a, total_adj)

    comparison: Dict[str, Any] = {}
    for name, preset in SCENARIO_PRESETS.items():
        other = run if name == req.scenario else run_model(invoices, a, preset.plus(req.adjustments))
        comparison[name] = {
            "label": SCENARIO_LABELS[name],
            "monthly_end_cash": [p["end_cash"] for p in other.monthly],
            "weekly_end_cash": [p["end_cash"] for p in other.weekly],
            "ending_cash": other.kpis_monthly["ending_cash"],
            "lowest_balance": other.kpis_monthly["lowest_balance"],
            "first_negative_date": other.kpis_monthly["first_negative_date"],
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
        "alerts": build_alerts(run, aging),
        "comparison": comparison,
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


def default_assumptions(rows: List[Dict[str, Any]], today: Optional[dt.date] = None) -> Dict[str, Any]:
    """Defaults derived from the invoice data.

    Receivables inputs (start date, revenue run-rate, days-to-pay) come from the
    data. Everything else (payroll, opex, debt, one-offs) is an *illustrative
    placeholder* scaled to the revenue run-rate so the model is usable out of
    the box; the UI flags these as needing the user's real numbers.
    """
    summary = ar.derive_data_summary(rows)
    collections, calibration = ar.calibrate_collections(ar.parse_invoices(rows))
    summary["collections_calibration"] = calibration
    today = today or dt.date.today()
    as_of = summary["as_of"] if summary["invoice_count"] else today
    revenue = summary["monthly_revenue"] or 100_000.0
    salary = 90_000.0
    burden = 22.0
    per_head_month = salary * (1 + burden / 100.0) / 12.0
    heads = max(1, round(revenue * 0.316 / per_head_month))

    assumptions = Assumptions(
        general=General(
            as_of=as_of,
            horizon_months=12,
            starting_cash=_round_to(revenue * 1.5, 1000),
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
            cogs_pct=40,
            dpo_days=30,
            opening_ap=round(revenue * 0.40 * 30 / 30),
        ),
        payroll=Payroll(
            headcount=heads,
            avg_salary=salary,
            burden_pct=burden,
            salary_growth_pct_annual=3,
            hires=[Hire(month=3, count=1), Hire(month=6, count=1)],
        ),
        opex=[
            OpexLine(name="Rent & facilities", kind="fixed", amount=_round_to(revenue * 0.052, 500)),
            OpexLine(name="Software & tools", kind="fixed", amount=_round_to(revenue * 0.026, 500)),
            OpexLine(name="Insurance & professional fees", kind="fixed", amount=_round_to(revenue * 0.049, 500)),
            OpexLine(name="Marketing", kind="pct_revenue", amount=4),
        ],
        loans=[
            Loan(
                name="Term loan",
                balance=_round_to(revenue * 1.2, 1000),
                annual_rate_pct=8,
                monthly_payment=_round_to(revenue * 0.026, 100),
            )
        ],
        one_time=[
            OneTimeItem(
                name="Equipment purchase",
                date=as_of + dt.timedelta(days=120),
                amount=-_round_to(revenue * 0.17, 1000),
                category="investing",
            )
        ],
        collections=collections,
    )
    return {"assumptions": assumptions, "data_summary": summary}
