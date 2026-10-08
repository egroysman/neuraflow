"""Receivables projection and data-derived defaults.

Open invoices are projected one by one:

* Expected pay date = invoice date + the customer's own average days-to-pay
  (falling back to the portfolio average for customers with no history).
* If that date has already passed, the invoice is "late versus its pattern" and
  is instead expected ``overdue_lag_days[bucket]`` after the start date.
* Expected cash = open amount x collectability for its aging bucket, so stale
  invoices contribute a haircut amount rather than the full face value.

Only payments made on or before the start date are used to learn customer
behaviour, so moving the start date back never leaks future information.
"""
from __future__ import annotations

import csv
import datetime as dt
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .models import Collections

BUCKETS = ["current", "d1_30", "d31_60", "d61_90", "d91_180", "d180_plus"]
BUCKET_LABELS = {
    "current": "Not yet due",
    "d1_30": "1-30 days past due",
    "d31_60": "31-60 days past due",
    "d61_90": "61-90 days past due",
    "d91_180": "91-180 days past due",
    "d180_plus": "180+ days past due",
}
FALLBACK_DAYS_TO_PAY = 45.0


def bucket_for(days_past_due: int) -> str:
    if days_past_due <= 0:
        return "current"
    if days_past_due <= 30:
        return "d1_30"
    if days_past_due <= 60:
        return "d31_60"
    if days_past_due <= 90:
        return "d61_90"
    if days_past_due <= 180:
        return "d91_180"
    return "d180_plus"


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #


def load_invoice_rows() -> List[Dict[str, Any]]:
    """Return raw invoice rows from the configured data source.

    Reuses the app's data-source layer so the model sees the same invoices as
    the chat assistant. Falls back to the bundled CSV when the active source
    does not expose raw rows (for example Snowflake).
    """
    try:
        from data_sources import get_data_source

        source = get_data_source()
        reader = getattr(source, "_read_rows", None)
        if callable(reader):
            rows = reader()
            if rows:
                return list(rows)
    except Exception:
        pass

    fallback = Path(__file__).resolve().parent.parent / "neuraflow_invoices.csv"
    env_path = os.getenv("DEFAULT_INVOICE_CSV_PATH")
    path = Path(env_path) if env_path and Path(env_path).exists() else fallback
    if not path.exists():
        return []
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))


@dataclass
class Invoice:
    invoice_id: str
    customer_id: str
    invoice_date: dt.date
    due_date: dt.date
    amount: float
    payment_date: Optional[dt.date]
    open_amount: float
    terms_days: int


def _float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _date(value: Any) -> Optional[dt.date]:
    if not value:
        return None
    try:
        return dt.date.fromisoformat(str(value).strip()[:10])
    except ValueError:
        return None


def parse_invoices(rows: Iterable[Dict[str, Any]]) -> List[Invoice]:
    invoices: List[Invoice] = []
    for row in rows:
        customer = str(row.get("CustomerID", "")).strip()
        invoice_date = _date(row.get("InvoiceDate"))
        amount = _float(row.get("InvoiceAmount"))
        if not customer or invoice_date is None or amount <= 0:
            continue
        terms = int(_float(row.get("TermsDays")) or 30)
        due_date = _date(row.get("DueDate")) or invoice_date + dt.timedelta(days=terms)
        payment_date = _date(row.get("PaymentDate"))
        status = str(row.get("Status", "")).strip().lower()
        if payment_date is None and status != "paid":
            open_amount = _float(row.get("OpenAmount")) or amount
        else:
            open_amount = 0.0
        invoices.append(
            Invoice(
                invoice_id=str(row.get("InvoiceID", "")),
                customer_id=customer,
                invoice_date=invoice_date,
                due_date=due_date,
                amount=amount,
                payment_date=payment_date,
                open_amount=open_amount,
                terms_days=terms,
            )
        )
    return invoices


# --------------------------------------------------------------------------- #
# Statistics derived from history
# --------------------------------------------------------------------------- #


def snapshot_date(invoices: List[Invoice], today: Optional[dt.date] = None) -> dt.date:
    """Newest invoice date: the natural 'as of' date for a forecast.

    Receivables are only complete up to the last invoice in the data. Using a
    later date (for example the latest payment) would leave the sales issued in
    between missing from the receivables book and understate near-term cash.
    """
    dates = [inv.invoice_date for inv in invoices]
    return max(dates) if dates else (today or dt.date.today())


def paid_before(invoices: List[Invoice], as_of: dt.date) -> List[Invoice]:
    return [i for i in invoices if i.payment_date and i.payment_date <= as_of]


def portfolio_days_to_pay(invoices: List[Invoice], as_of: dt.date) -> float:
    days = [(i.payment_date - i.invoice_date).days for i in paid_before(invoices, as_of)]
    return mean(days) if days else FALLBACK_DAYS_TO_PAY


def customer_stats(invoices: List[Invoice], as_of: dt.date) -> Dict[str, Dict[str, Any]]:
    by_customer: Dict[str, List[int]] = defaultdict(list)
    late: Dict[str, List[int]] = defaultdict(list)
    for inv in paid_before(invoices, as_of):
        by_customer[inv.customer_id].append((inv.payment_date - inv.invoice_date).days)
        late[inv.customer_id].append((inv.payment_date - inv.due_date).days)
    return {
        cust: {
            "avg_days_to_pay": mean(days),
            "avg_days_late": mean(late[cust]),
            "paid_count": len(days),
        }
        for cust, days in by_customer.items()
    }


def trailing_monthly_revenue(invoices: List[Invoice], months: int = 3) -> float:
    """Average invoiced revenue over the last complete calendar months.

    The month containing the newest invoice is treated as partial and skipped
    unless that invoice falls on the last day of its month.
    """
    if not invoices:
        return 0.0
    last = max(i.invoice_date for i in invoices)
    next_day = last + dt.timedelta(days=1)
    partial_month = (last.year, last.month) if next_day.month == last.month else None
    totals: Dict[tuple, float] = defaultdict(float)
    for inv in invoices:
        totals[(inv.invoice_date.year, inv.invoice_date.month)] += inv.amount
    complete = sorted(k for k in totals if k != partial_month)
    chosen = complete[-months:]
    if not chosen:
        return sum(totals.values())
    return sum(totals[k] for k in chosen) / len(chosen)


def open_invoices_at(invoices: List[Invoice], as_of: dt.date) -> List[Invoice]:
    """Invoices that were issued by ``as_of`` and not yet paid on that date."""
    result = []
    for inv in invoices:
        if inv.invoice_date > as_of:
            continue
        if inv.payment_date is None:
            if inv.open_amount > 0:
                result.append(inv)
        elif inv.payment_date > as_of:
            result.append(
                Invoice(
                    inv.invoice_id, inv.customer_id, inv.invoice_date, inv.due_date,
                    inv.amount, inv.payment_date, inv.amount, inv.terms_days,
                )
            )
    return result


# --------------------------------------------------------------------------- #
# Projection
# --------------------------------------------------------------------------- #


def project_open_invoices(
    invoices: List[Invoice],
    as_of: dt.date,
    collections: Collections,
    delay_days: int = 0,
    extra_bad_debt_pct: float = 0.0,
) -> List[Dict[str, Any]]:
    stats = customer_stats(invoices, as_of)
    portfolio = portfolio_days_to_pay(invoices, as_of)
    collectability = collections.collectability_pct.model_dump()
    lags = collections.overdue_lag_days.model_dump()
    haircut = max(0.0, 1.0 - extra_bad_debt_pct / 100.0)

    projected = []
    for inv in open_invoices_at(invoices, as_of):
        days_past_due = (as_of - inv.due_date).days
        bucket = bucket_for(days_past_due)
        avg_days = stats.get(inv.customer_id, {}).get("avg_days_to_pay", portfolio)
        pattern_date = inv.invoice_date + dt.timedelta(days=round(avg_days))
        if pattern_date > as_of:
            expected = pattern_date
        else:
            expected = as_of + dt.timedelta(days=round(lags[bucket]))
        expected += dt.timedelta(days=delay_days)
        expected = max(expected, as_of + dt.timedelta(days=1))
        probability = collectability[bucket] / 100.0 * haircut
        projected.append(
            {
                "invoice_id": inv.invoice_id,
                "customer_id": inv.customer_id,
                "open_amount": inv.open_amount,
                "due_date": inv.due_date,
                "days_past_due": days_past_due,
                "bucket": bucket,
                "probability": probability,
                "expected_date": expected,
                "expected_amount": inv.open_amount * probability,
            }
        )
    return projected


def calibrate_collections(
    invoices: List[Invoice],
    follow_days: int = 90,
    step_days: int = 30,
    min_snapshots: int = 3,
) -> Tuple[Collections, Dict[str, Any]]:
    """Learn collectability and payment lag by aging bucket from history.

    The history is replayed at monthly snapshot dates. At each snapshot every
    open invoice is bucketed by days past due, and we record whether (and how
    soon) it was actually paid within ``follow_days``. Only snapshots with a
    full follow-up window are used, so recent invoices are never miscounted as
    unpaid just because the data ends.

    Buckets with no observations inherit the next-better bucket's rate, capped
    at the generic default, so an unseen "180+ days" bucket is never assumed
    to collect better than "91-180 days". With too little history the generic
    defaults are returned unchanged.
    """
    defaults = Collections()
    default_pct = defaults.collectability_pct.model_dump()
    default_lag = defaults.overdue_lag_days.model_dump()
    meta: Dict[str, Any] = {
        "calibrated": False,
        "follow_days": follow_days,
        "snapshots": 0,
        "observed_open_amount": {b: 0.0 for b in BUCKETS},
    }
    paid_dates = [i.payment_date for i in invoices if i.payment_date]
    if not invoices or not paid_dates:
        return defaults, meta

    first = min(i.invoice_date for i in invoices)
    last_pay = max(paid_dates)
    snapshots: List[dt.date] = []
    cursor = first + dt.timedelta(days=step_days)
    while cursor <= last_pay - dt.timedelta(days=follow_days):
        snapshots.append(cursor)
        cursor += dt.timedelta(days=step_days)
    meta["snapshots"] = len(snapshots)
    if len(snapshots) < min_snapshots:
        return defaults, meta

    open_amt = {b: 0.0 for b in BUCKETS}
    paid_amt = {b: 0.0 for b in BUCKETS}
    lags: Dict[str, List[int]] = {b: [] for b in BUCKETS}
    for snap in snapshots:
        for inv in open_invoices_at(invoices, snap):
            bucket = bucket_for((snap - inv.due_date).days)
            open_amt[bucket] += inv.open_amount
            if inv.payment_date and inv.payment_date <= snap + dt.timedelta(days=follow_days):
                paid_amt[bucket] += inv.open_amount
                lags[bucket].append((inv.payment_date - snap).days)
    meta["observed_open_amount"] = open_amt

    pct: Dict[str, float] = {}
    lag: Dict[str, float] = {}
    previous = 100.0
    for bucket in BUCKETS:
        if open_amt[bucket] > 0:
            rate = 100.0 * paid_amt[bucket] / open_amt[bucket]
        else:
            rate = min(previous, default_pct[bucket])
        pct[bucket] = round(min(rate, previous if bucket != "current" else 100.0), 1)
        previous = pct[bucket]
        lag[bucket] = (
            float(sorted(lags[bucket])[len(lags[bucket]) // 2])
            if lags[bucket]
            else default_lag[bucket]
        )
    meta["calibrated"] = True
    return Collections(collectability_pct=pct, overdue_lag_days=lag), meta


def risk_label(past_due_90_share: float, avg_days_late: float) -> str:
    if past_due_90_share > 0.5 or avg_days_late > 30:
        return "High"
    if past_due_90_share > 0.2 or avg_days_late > 10:
        return "Medium"
    return "Low"


def summarize_customers(
    projected: List[Dict[str, Any]],
    invoices: List[Invoice],
    as_of: dt.date,
    horizon_end: dt.date,
    top: int = 15,
) -> List[Dict[str, Any]]:
    stats = customer_stats(invoices, as_of)
    grouped: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in projected:
        grouped[row["customer_id"]].append(row)

    rows = []
    for cust, items in grouped.items():
        open_total = sum(i["open_amount"] for i in items)
        severe = sum(i["open_amount"] for i in items if i["days_past_due"] > 90)
        cust_stats = stats.get(cust, {})
        rows.append(
            {
                "customer_id": cust,
                "open_invoices": len(items),
                "open_amount": open_total,
                "expected_in_horizon": sum(
                    i["expected_amount"] for i in items if i["expected_date"] < horizon_end
                ),
                "avg_days_to_pay": cust_stats.get("avg_days_to_pay"),
                "oldest_days_past_due": max(i["days_past_due"] for i in items),
                "risk": risk_label(
                    severe / open_total if open_total else 0.0,
                    cust_stats.get("avg_days_late", 0.0),
                ),
            }
        )
    rows.sort(key=lambda r: r["open_amount"], reverse=True)
    return rows[:top]


def aging_summary(projected: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    totals = {b: 0.0 for b in BUCKETS}
    counts = {b: 0 for b in BUCKETS}
    for row in projected:
        totals[row["bucket"]] += row["open_amount"]
        counts[row["bucket"]] += 1
    return [
        {"bucket": b, "label": BUCKET_LABELS[b], "open_amount": totals[b], "invoices": counts[b]}
        for b in BUCKETS
    ]


# --------------------------------------------------------------------------- #
# Data-derived defaults
# --------------------------------------------------------------------------- #


def derive_data_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    invoices = parse_invoices(rows)
    as_of = snapshot_date(invoices)
    open_now = open_invoices_at(invoices, as_of)
    return {
        "invoice_count": len(invoices),
        "customer_count": len({i.customer_id for i in invoices}),
        "as_of": as_of,
        "first_invoice_date": min((i.invoice_date for i in invoices), default=None),
        "last_invoice_date": max((i.invoice_date for i in invoices), default=None),
        "monthly_revenue": trailing_monthly_revenue(invoices),
        "dso_days": portfolio_days_to_pay(invoices, as_of),
        "open_ar": sum(i.open_amount for i in open_now),
        "open_invoice_count": len(open_now),
    }
