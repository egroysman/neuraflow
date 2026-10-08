"""Micro trends: what the company's own invoices and bills say is changing.

Everything here uses only data on or before the start date. Complete calendar
months are compared (the month containing the start date is partial and is
shown but left out of the comparisons).
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from statistics import mean
from typing import Any, Dict, List, Optional

from . import ap, ar

MIN_MONTHS_FOR_SEASONALITY = 12


def _month_key(d: dt.date) -> str:
    return d.strftime("%Y-%m")


def _month_end(year: int, month: int) -> dt.date:
    nxt = dt.date(year + (month == 12), (month % 12) + 1, 1)
    return nxt - dt.timedelta(days=1)


def _months_between(first: dt.date, last: dt.date) -> List[str]:
    out, y, m = [], first.year, first.month
    while (y, m) <= (last.year, last.month):
        out.append(f"{y:04d}-{m:02d}")
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _pct_change(current: Optional[float], previous: Optional[float]) -> Optional[float]:
    if current is None or previous in (None, 0):
        return None
    return (current / previous - 1.0) * 100.0


def _avg(values: List[Optional[float]]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    return mean(vals) if vals else None


def monthly_series(invoices: List[ar.Invoice], bills: List[ap.Bill], as_of: dt.date) -> List[Dict[str, Any]]:
    dates = [i.invoice_date for i in invoices if i.invoice_date <= as_of]
    if not dates:
        return []
    first = min(dates)
    keys = _months_between(first, as_of)
    first_partial = first.day > 5  # data starts mid-month
    rows: Dict[str, Dict[str, Any]] = {
        k: {"month": k,
            "partial": k == _month_key(as_of) or (first_partial and k == keys[0]),
            "partial_reason": "end" if k == _month_key(as_of) else ("start" if first_partial and k == keys[0] else None),
            "invoiced": 0.0, "invoice_count": 0,
            "collected": 0.0, "paid_days": [], "on_time": [], "billed": 0.0, "bill_paid_days": []}
        for k in keys
    }
    for inv in invoices:
        if inv.invoice_date <= as_of:
            r = rows[_month_key(inv.invoice_date)]
            r["invoiced"] += inv.amount
            r["invoice_count"] += 1
        if inv.payment_date and inv.payment_date <= as_of and _month_key(inv.payment_date) in rows:
            r = rows[_month_key(inv.payment_date)]
            r["collected"] += inv.amount
            r["paid_days"].append((inv.payment_date - inv.invoice_date).days)
            r["on_time"].append(1.0 if inv.payment_date <= inv.due_date else 0.0)
    for b in bills:
        if b.bill_date <= as_of and _month_key(b.bill_date) in rows:
            rows[_month_key(b.bill_date)]["billed"] += b.amount
        if b.payment_date and b.payment_date <= as_of and _month_key(b.payment_date) in rows:
            rows[_month_key(b.payment_date)]["bill_paid_days"].append((b.payment_date - b.bill_date).days)

    out = []
    for k in keys:
        r = rows[k]
        year, month = int(k[:4]), int(k[5:])
        snapshot = min(_month_end(year, month), as_of)
        open_inv = ar.open_invoices_at(invoices, snapshot)
        open_total = sum(i.open_amount for i in open_inv)
        past_due = sum(i.open_amount for i in open_inv if (snapshot - i.due_date).days > 0)
        out.append(
            {
                "month": k,
                "label": dt.date(year, month, 1).strftime("%b %Y"),
                "partial": r["partial"],
                "partial_reason": r["partial_reason"],
                "invoiced": r["invoiced"],
                "invoice_count": r["invoice_count"],
                "collected": r["collected"],
                "avg_days_to_pay": mean(r["paid_days"]) if r["paid_days"] else None,
                "on_time_pct": 100.0 * mean(r["on_time"]) if r["on_time"] else None,
                "open_ar": open_total,
                "past_due_pct": 100.0 * past_due / open_total if open_total else None,
                "vendor_billed": r["billed"],
                "vendor_days_to_pay": mean(r["bill_paid_days"]) if r["bill_paid_days"] else None,
            }
        )
    return out


def _signal(key, label, current, previous, unit, higher_is_good, as_change="pct", note=""):
    if current is None or previous is None:
        return None
    change = _pct_change(current, previous) if as_change == "pct" else current - previous
    if change is None:
        return None
    flat = abs(change) < (1.0 if as_change == "pct" else 0.5)
    tone = "neutral" if flat else ("good" if (change > 0) == higher_is_good else "bad")
    return {
        "key": key,
        "label": label,
        "current": current,
        "previous": previous,
        "change": change,
        "change_unit": "%" if as_change == "pct" else unit,
        "unit": unit,
        "tone": tone,
        "note": note,
    }


def build_signals(series: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    complete = [m for m in series if not m["partial"]]
    if len(complete) < 4:
        return []
    window = min(3, len(complete) // 2)
    cur, prev = complete[-window:], complete[-2 * window : -window]
    col = lambda rows, key: _avg([r[key] for r in rows])  # noqa: E731
    total = lambda rows, key: sum(r[key] for r in rows)  # noqa: E731
    candidates = [
        _signal("revenue", "Invoiced revenue", total(cur, "invoiced"), total(prev, "invoiced"), "$", True),
        _signal("collections", "Cash collected", total(cur, "collected"), total(prev, "collected"), "$", True),
        _signal("days_to_pay", "Customer days to pay", col(cur, "avg_days_to_pay"), col(prev, "avg_days_to_pay"), "days", False, "abs"),
        _signal("on_time", "Invoices paid on time", col(cur, "on_time_pct"), col(prev, "on_time_pct"), "pts", True, "abs"),
        _signal("past_due", "Receivables past due", col(cur, "past_due_pct"), col(prev, "past_due_pct"), "pts", False, "abs"),
        _signal("vendor_spend", "Vendor spend", total(cur, "vendor_billed") or None, total(prev, "vendor_billed") or None, "$", False),
        _signal("vendor_days", "Days you take to pay vendors", col(cur, "vendor_days_to_pay"), col(prev, "vendor_days_to_pay"), "days", True, "abs",
                "Higher keeps cash longer, but strains vendors"),
    ]
    signals = [s for s in candidates if s]
    for s in signals:
        s["window_months"] = window
    return signals


def implied_growth(series: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Monthly revenue growth from a log-linear fit over complete months."""
    pts = [(i, m["invoiced"]) for i, m in enumerate(m for m in series if not m["partial"]) if m["invoiced"] > 0]
    if len(pts) < 4:
        return None
    xs = [p[0] for p in pts]
    ys = [math.log(p[1]) for p in pts]
    mx, my = mean(xs), mean(ys)
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom
    return {"monthly_growth_pct": round((math.exp(slope) - 1.0) * 100.0, 2), "months_used": len(pts)}


def concentration(invoices: List[ar.Invoice], as_of: dt.date, months: int = 6) -> Dict[str, Any]:
    start = as_of - dt.timedelta(days=30 * months)
    totals: Dict[str, float] = defaultdict(float)
    for inv in invoices:
        if start < inv.invoice_date <= as_of:
            totals[inv.customer_id] += inv.amount
    grand = sum(totals.values())
    ranked = sorted(totals.items(), key=lambda kv: -kv[1])
    return {
        "window_months": months,
        "customers": len(totals),
        "top1_pct": round(100 * ranked[0][1] / grand, 1) if grand else 0.0,
        "top5_pct": round(100 * sum(v for _, v in ranked[:5]) / grand, 1) if grand else 0.0,
        "top_customers": [{"customer_id": c, "amount": v, "share_pct": round(100 * v / grand, 1)} for c, v in ranked[:5]]
        if grand else [],
    }


def seasonality(series: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    complete = [m for m in series if not m["partial"] and m["invoiced"] > 0]
    if len(complete) < MIN_MONTHS_FOR_SEASONALITY:
        return None
    overall = mean(m["invoiced"] for m in complete)
    by_month: Dict[int, List[float]] = defaultdict(list)
    for m in complete:
        by_month[int(m["month"][5:])].append(m["invoiced"] / overall)
    return {"index": [{"month": mo, "index": round(mean(v), 3)} for mo, v in sorted(by_month.items())]}


def build_trends(invoices: List[ar.Invoice], bills: List[ap.Bill], as_of: dt.date) -> Dict[str, Any]:
    series = monthly_series(invoices, bills, as_of)
    season = seasonality(series)
    caveats = []
    for m in series:
        if m["partial"]:
            where = "the start" if m["partial_reason"] == "start" else "the end"
            caveats.append(f"{m['label']} is a partial month at {where} of the data, so it is shown but left out of the comparisons.")
    caveats.append(
        "Days to pay and on-time % are measured on payments received in each month, so the newest "
        "months only reflect invoices that have already been paid."
    )
    return {
        "as_of": as_of,
        "caveats": caveats,
        "months": series,
        "signals": build_signals(series),
        "implied": {
            "growth": implied_growth(series),
            "days_to_pay": ar.portfolio_days_to_pay(invoices, as_of) if invoices else None,
        },
        "concentration": concentration(invoices, as_of),
        "seasonality": season,
        "seasonality_note": None
        if season
        else f"Seasonality needs at least {MIN_MONTHS_FOR_SEASONALITY} complete months of history; "
        f"this data has {len([m for m in series if not m['partial']])}.",
    }
