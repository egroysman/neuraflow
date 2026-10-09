"""Accounts payable: vendor bills, aging and payment projection.

Open bills are projected one by one. A bill is expected to be paid on its due
date plus ``payment_lag_days`` (how late or early the business typically pays)
plus any scenario DPO stretch. Bills already past that date are paid within
``overdue_catchup_days`` of the start date, spread by how overdue they are.

Vendor behaviour (average days paid versus due) is learned only from payments
made on or before the start date, so it never leaks future information.
"""
from __future__ import annotations

import csv
import datetime as dt
import os
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from typing import Any, Dict, Iterable, List, Optional

from .ar import _date, _float  # shared tolerant parsers

AP_BUCKETS = ["current", "d1_30", "d31_60", "d61_90", "d90_plus"]
AP_BUCKET_LABELS = {
    "current": "Not yet due",
    "d1_30": "1-30 days past due",
    "d31_60": "31-60 days past due",
    "d61_90": "61-90 days past due",
    "d90_plus": "90+ days past due",
}


def ap_bucket(days_past_due: int) -> str:
    if days_past_due <= 0:
        return "current"
    if days_past_due <= 30:
        return "d1_30"
    if days_past_due <= 60:
        return "d31_60"
    if days_past_due <= 90:
        return "d61_90"
    return "d90_plus"


@dataclass
class Bill:
    bill_id: str
    vendor_id: str
    vendor_name: str
    category: str
    bill_date: dt.date
    due_date: dt.date
    amount: float
    payment_date: Optional[dt.date]
    open_amount: float
    terms_days: int


def load_bill_rows() -> List[Dict[str, Any]]:
    """Raw bill rows from the bundled sample dataset (or DEFAULT_BILLS_CSV_PATH)."""
    fallback = Path(__file__).resolve().parent.parent / "neuraflow_bills.csv"
    env_path = os.getenv("DEFAULT_BILLS_CSV_PATH")
    path = Path(env_path) if env_path and Path(env_path).exists() else fallback
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if path == fallback:
        from . import sample

        rows = sample.shift_rows(rows, "BillDate", sample.BILL_OTHERS)
    return rows


def parse_bills(rows: Iterable[Dict[str, Any]]) -> List[Bill]:
    bills: List[Bill] = []
    for row in rows:
        bill_date, due = _date(row.get("BillDate")), _date(row.get("DueDate"))
        if bill_date is None:
            continue
        amount = _float(row.get("BillAmount"))
        if amount <= 0:
            continue
        terms = int(_float(row.get("TermsDays")) or 30)
        due = due or bill_date + dt.timedelta(days=terms)
        paid = _date(row.get("PaymentDate"))
        open_amount = _float(row.get("OpenAmount"))
        if paid is None and open_amount <= 0:
            open_amount = amount
        bills.append(
            Bill(
                bill_id=str(row.get("BillID", "")),
                vendor_id=str(row.get("VendorID", "")),
                vendor_name=str(row.get("VendorName") or row.get("VendorID") or "Unknown vendor"),
                category=str(row.get("Category") or "Other"),
                bill_date=bill_date,
                due_date=due,
                amount=amount,
                payment_date=paid,
                open_amount=open_amount,
                terms_days=terms,
            )
        )
    return bills


def snapshot_date(bills: List[Bill]) -> Optional[dt.date]:
    return max((b.bill_date for b in bills), default=None)


def open_bills_at(bills: List[Bill], as_of: dt.date) -> List[Bill]:
    """Bills dated on or before ``as_of`` that were still unpaid on that date."""
    result = []
    for b in bills:
        if b.bill_date > as_of:
            continue
        if b.payment_date is None:
            if b.open_amount > 0:
                result.append(b)
        elif b.payment_date > as_of:
            result.append(
                Bill(b.bill_id, b.vendor_id, b.vendor_name, b.category, b.bill_date,
                     b.due_date, b.amount, b.payment_date, b.amount, b.terms_days)
            )
    return result


def vendor_stats(bills: List[Bill], as_of: dt.date) -> Dict[str, Dict[str, Any]]:
    paid: Dict[str, List[Bill]] = defaultdict(list)
    for b in bills:
        if b.payment_date and b.payment_date <= as_of:
            paid[b.vendor_id].append(b)
    return {
        vid: {
            "avg_days_to_pay": mean((b.payment_date - b.bill_date).days for b in items),
            "avg_days_vs_due": mean((b.payment_date - b.due_date).days for b in items),
            "paid_count": len(items),
        }
        for vid, items in paid.items()
    }


def typical_lag_days(bills: List[Bill], as_of: dt.date) -> float:
    """Average days after the due date that bills were historically paid."""
    lags = [(b.payment_date - b.due_date).days for b in bills if b.payment_date and b.payment_date <= as_of]
    return round(mean(lags), 1) if lags else 0.0


def actual_dpo(bills: List[Bill], as_of: dt.date) -> Optional[float]:
    """Amount-weighted days from bill date to payment, over bills paid by ``as_of``."""
    paid = [b for b in bills if b.payment_date and b.payment_date <= as_of]
    total = sum(b.amount for b in paid)
    if total <= 0:
        return None
    return sum((b.payment_date - b.bill_date).days * b.amount for b in paid) / total


def project_open_bills(
    bills: List[Bill],
    as_of: dt.date,
    payment_lag_days: float = 0.0,
    overdue_catchup_days: int = 14,
    dpo_change_days: int = 0,
    top_vendor_delay_days: int = 0,
) -> List[Dict[str, Any]]:
    projected = []
    first_day = as_of + dt.timedelta(days=1)
    open_bills = open_bills_at(bills, as_of)
    top_vendor = None
    if top_vendor_delay_days:
        owed: Dict[str, float] = {}
        for b in open_bills:
            owed[b.vendor_id] = owed.get(b.vendor_id, 0.0) + b.open_amount
        top_vendor = max(owed, key=owed.get) if owed else None
    for b in open_bills:
        days_past_due = (as_of - b.due_date).days
        planned = b.due_date + dt.timedelta(days=round(payment_lag_days + dpo_change_days))
        if planned <= as_of:
            # Late already: clear it within the catch-up window, oldest first.
            overdue = max(1, (as_of - b.due_date).days)
            share = min(1.0, overdue / 90.0)
            planned = as_of + dt.timedelta(days=round(overdue_catchup_days * (1.0 - 0.7 * share)))
        if top_vendor is not None and b.vendor_id == top_vendor:
            planned += dt.timedelta(days=top_vendor_delay_days)
        planned = max(planned, first_day)
        projected.append(
            {
                "bill_id": b.bill_id,
                "vendor_id": b.vendor_id,
                "vendor_name": b.vendor_name,
                "category": b.category,
                "bill_date": b.bill_date,
                "due_date": b.due_date,
                "days_past_due": days_past_due,
                "bucket": ap_bucket(days_past_due),
                "open_amount": b.open_amount,
                "expected_date": planned,
            }
        )
    projected.sort(key=lambda p: (p["expected_date"], p["bill_id"]))
    return projected


def aging_summary(projected: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = {k: {"bucket": k, "label": AP_BUCKET_LABELS[k], "open_amount": 0.0, "bills": 0} for k in AP_BUCKETS}
    for p in projected:
        rows[p["bucket"]]["open_amount"] += p["open_amount"]
        rows[p["bucket"]]["bills"] += 1
    return [rows[k] for k in AP_BUCKETS]


def summarize_ap(
    bills: List[Bill],
    projected: List[Dict[str, Any]],
    as_of: dt.date,
    horizon_end: dt.date,
    top_n: int = 10,
) -> Dict[str, Any]:
    stats = vendor_stats(bills, as_of)
    open_total = sum(p["open_amount"] for p in projected)
    overdue_total = sum(p["open_amount"] for p in projected if p["days_past_due"] > 0)
    by_vendor: Dict[str, Dict[str, Any]] = {}
    for p in projected:
        v = by_vendor.setdefault(
            p["vendor_id"],
            {"vendor_id": p["vendor_id"], "vendor_name": p["vendor_name"], "category": p["category"],
             "open_amount": 0.0, "bills": 0, "oldest_days_past_due": -9999},
        )
        v["open_amount"] += p["open_amount"]
        v["bills"] += 1
        v["oldest_days_past_due"] = max(v["oldest_days_past_due"], p["days_past_due"])
    vendors = sorted(by_vendor.values(), key=lambda v: -v["open_amount"])
    for v in vendors:
        s = stats.get(v["vendor_id"])
        v["avg_days_to_pay"] = round(s["avg_days_to_pay"], 1) if s else None
        v["avg_days_vs_due"] = round(s["avg_days_vs_due"], 1) if s else None
        v["share_pct"] = round(100 * v["open_amount"] / open_total, 1) if open_total else 0.0
        v["oldest_days_past_due"] = max(0, v["oldest_days_past_due"])

    # Payments by month of the forecast, from the open bills only.
    months: Dict[str, float] = defaultdict(float)
    for p in projected:
        if p["expected_date"] < horizon_end:
            months[p["expected_date"].strftime("%Y-%m")] += p["open_amount"]
    category_totals: Dict[str, float] = defaultdict(float)
    for p in projected:
        category_totals[p["category"]] += p["open_amount"]

    spend_by_month: Dict[str, float] = defaultdict(float)
    for b in bills:
        if b.bill_date <= as_of:
            spend_by_month[b.bill_date.strftime("%Y-%m")] += b.amount
    return {
        "bill_count": len([b for b in bills if b.bill_date <= as_of]),
        "vendor_count": len({b.vendor_id for b in bills}),
        "open_total": open_total,
        "open_bills": len(projected),
        "overdue_total": overdue_total,
        "overdue_pct": round(100 * overdue_total / open_total, 1) if open_total else 0.0,
        "actual_dpo_days": round(actual_dpo(bills, as_of), 1) if actual_dpo(bills, as_of) is not None else None,
        "typical_lag_days": typical_lag_days(bills, as_of),
        "aging": aging_summary(projected),
        "vendors": vendors[:top_n],
        "top3_share_pct": round(sum(v["share_pct"] for v in vendors[:3]), 1),
        "by_category": [
            {"category": c, "open_amount": amt}
            for c, amt in sorted(category_totals.items(), key=lambda kv: -kv[1])
        ],
        "due_by_month": [{"month": m, "amount": amt} for m, amt in sorted(months.items())],
        "upcoming": [
            {k: p[k] for k in ("bill_id", "vendor_name", "category", "due_date", "expected_date", "days_past_due", "open_amount")}
            for p in projected[:12]
        ],
        "monthly_spend": [{"month": m, "amount": a} for m, a in sorted(spend_by_month.items())],
    }


def derive_ap_summary(bills: List[Bill], as_of: dt.date) -> Dict[str, Any]:
    open_ = open_bills_at(bills, as_of)
    return {
        "bill_count": len(bills),
        "vendor_count": len({b.vendor_id for b in bills}),
        "open_ap": sum(b.open_amount for b in open_),
        "open_bill_count": len(open_),
        "typical_lag_days": typical_lag_days(bills, as_of),
        "actual_dpo_days": round(actual_dpo(bills, as_of), 1) if actual_dpo(bills, as_of) is not None else None,
        "first_bill_date": min((b.bill_date for b in bills), default=None),
        "last_bill_date": snapshot_date(bills),
    }
