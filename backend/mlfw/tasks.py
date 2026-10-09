"""Point-in-time datasets and task definitions for the first models.

Every feature is computed from what was known on the row's prediction date. That is the rule that keeps
back-tests honest: a model is never shown anything from after the moment it would have had to decide.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from statistics import median
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np
from sklearn.ensemble import GradientBoostingClassifier, GradientBoostingRegressor
from sklearn.linear_model import LogisticRegression, Ridge
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from cashflow import credit
from cashflow.ap import Bill
from cashflow.ar import Invoice

from .core import BaselineSpec, Dataset, ModelSpec, Row, SEED

LATE_DAYS = 10

INVOICE_FEATURES = [
    "score_timing", "score_late_rate", "score_open", "score_consistency", "score_trend",
    "avg_days_late", "late_rate_pct", "spread_days", "trend_days", "trend_known", "observations",
    "past_due_ratio", "oldest_past_due", "log_amount", "amount_vs_median", "terms_days",
    "due_month_sin", "due_month_cos", "prior_invoices",
]
COMPONENT_FEATURES = ["score_timing", "score_late_rate", "score_open", "score_consistency", "score_trend"]
COMPONENT_KEYS = {"score_timing": "timing", "score_late_rate": "late_rate", "score_open": "open_exposure",
                  "score_consistency": "consistency", "score_trend": "trend"}
BILL_CATEGORIES = ["Cost of sales", "Facilities", "Professional services", "Software", "Insurance", "Marketing", "Maintenance"]
BILL_FEATURES = ["vendor_prior_n", "vendor_mean_lag", "vendor_std_lag", "vendor_last_lag", "log_amount", "terms_days",
                 "due_month_sin", "due_month_cos"] + [f"cat_{i}" for i in range(len(BILL_CATEGORIES) + 1)]


def _month_angles(d: dt.date) -> Tuple[float, float]:
    a = 2 * math.pi * (d.month - 1) / 12.0
    return math.sin(a), math.cos(a)


# --------------------------------------------------------------------------- #
# Invoice rows (timing, learned credit score)
# --------------------------------------------------------------------------- #


def invoice_features(items: Sequence[Invoice], inv: Invoice, as_of: dt.date) -> Dict[str, float]:
    s = credit.score_customer(items, as_of)
    comp = {c["key"]: c["score"] for c in s["components"]}
    prior_amounts = [i.amount for i in items if i.invoice_date < inv.invoice_date]
    typical = median(prior_amounts) if prior_amounts else inv.amount
    sin, cos = _month_angles(inv.due_date)
    open_amt = s["open_amount"] or 0.0
    f = {name: comp[key] for name, key in COMPONENT_KEYS.items()}
    f.update(
        score=s["score"],
        avg_days_late=s["avg_days_late"],
        late_rate_pct=s["late_rate_pct"],
        spread_days=s["spread_days"],
        trend_days=s["trend_days"] or 0.0,
        trend_known=0.0 if s["trend_days"] is None else 1.0,
        observations=float(s["observations"]),
        past_due_ratio=(s["past_due_amount"] / open_amt) if open_amt else 0.0,
        oldest_past_due=float(s["oldest_days_past_due"]),
        log_amount=math.log1p(inv.amount),
        amount_vs_median=(inv.amount / typical) if typical else 1.0,
        terms_days=float(inv.terms_days),
        due_month_sin=sin,
        due_month_cos=cos,
        prior_invoices=float(len(prior_amounts)),
    )
    return f


def build_invoice_datasets(invoices: Sequence[Invoice], late_days: int = LATE_DAYS) -> Tuple[Dataset, Dataset]:
    """(late-or-not dataset, days-late dataset), one row per invoice at the moment it was issued."""
    paid_dates = [i.payment_date for i in invoices if i.payment_date]
    if not paid_dates:
        return Dataset("invoice_late", "classification", [], INVOICE_FEATURES), Dataset("invoice_days_late", "regression", [], INVOICE_FEATURES)
    data_end = max(paid_dates)
    by_customer: Dict[str, List[Invoice]] = defaultdict(list)
    for i in invoices:
        by_customer[i.customer_id].append(i)

    cls_rows: List[Row] = []
    reg_rows: List[Row] = []
    censored = 0
    for inv in invoices:
        feats = invoice_features(by_customer[inv.customer_id], inv, inv.invoice_date)
        meta = {"customer": inv.customer_id, "amount": inv.amount, "due_date": str(inv.due_date)}
        threshold = inv.due_date + dt.timedelta(days=late_days)
        if inv.payment_date is not None:
            days_late = (inv.payment_date - inv.due_date).days
            late = days_late > late_days
            known = min(inv.payment_date, threshold + dt.timedelta(days=1)) if late else inv.payment_date
            cls_rows.append(Row(inv.invoice_id, inv.customer_id, inv.invoice_date, known, feats, float(late), meta))
            reg_rows.append(Row(inv.invoice_id, inv.customer_id, inv.invoice_date, inv.payment_date, feats, float(max(-15, min(120, days_late))), meta))
        elif (data_end - inv.due_date).days > late_days:
            cls_rows.append(Row(inv.invoice_id, inv.customer_id, inv.invoice_date, threshold + dt.timedelta(days=1), feats, 1.0, meta))
        else:
            censored += 1  # unpaid and not old enough to call late: outcome genuinely unknown
    c = Dataset(
        "invoice_late", "classification", cls_rows, INVOICE_FEATURES,
        [f"Late means paid more than {late_days} days after the due date, or still unpaid that long after.",
         f"{censored} invoices were left out because they are too recent to judge."],
    )
    r = Dataset(
        "invoice_days_late", "regression", reg_rows, INVOICE_FEATURES,
        ["Only paid invoices have a payment date, so unpaid invoices are left out. That makes this view look more optimistic than reality."],
    )
    return c, r


# --------------------------------------------------------------------------- #
# Bill rows
# --------------------------------------------------------------------------- #


def build_bill_dataset(bills: Sequence[Bill]) -> Dataset:
    by_vendor: Dict[str, List[Bill]] = defaultdict(list)
    for b in bills:
        by_vendor[b.vendor_id].append(b)
    rows: List[Row] = []
    for b in bills:
        if b.payment_date is None:
            continue
        prior = sorted(
            ((p.payment_date, (p.payment_date - p.due_date).days) for p in by_vendor[b.vendor_id]
             if p.payment_date is not None and p.payment_date <= b.bill_date and p is not b)
        )
        lags = [lag for _, lag in prior]
        sin, cos = _month_angles(b.due_date)
        cat = BILL_CATEGORIES.index(b.category) if b.category in BILL_CATEGORIES else len(BILL_CATEGORIES)
        f = {
            "vendor_prior_n": float(len(lags)),
            "vendor_mean_lag": float(np.mean(lags)) if lags else 0.0,
            "vendor_std_lag": float(np.std(lags)) if len(lags) > 1 else 0.0,
            "vendor_last_lag": float(lags[-1]) if lags else 0.0,
            "log_amount": math.log1p(b.amount),
            "terms_days": float(b.terms_days),
            "due_month_sin": sin,
            "due_month_cos": cos,
        }
        for i in range(len(BILL_CATEGORIES) + 1):
            f[f"cat_{i}"] = 1.0 if i == cat else 0.0
        lag = (b.payment_date - b.due_date).days
        rows.append(Row(b.bill_id, b.vendor_id, b.bill_date, b.payment_date, f, float(max(-15, min(60, lag))),
                        {"vendor": b.vendor_name, "amount": b.amount}))
    return Dataset("bill_days_late", "regression", rows, BILL_FEATURES,
                   ["Only paid bills have a payment date. Few bills exist, so conclusions here are weak."])


# --------------------------------------------------------------------------- #
# Estimators
# --------------------------------------------------------------------------- #


def logistic():
    return make_pipeline(StandardScaler(), LogisticRegression(C=0.5, max_iter=2000))


def gbm_classifier():
    return GradientBoostingClassifier(n_estimators=120, max_depth=2, learning_rate=0.05, subsample=0.8, random_state=SEED)


def ridge():
    return make_pipeline(StandardScaler(), Ridge(alpha=10.0))


def gbm_regressor():
    return GradientBoostingRegressor(n_estimators=120, max_depth=2, learning_rate=0.05, subsample=0.8, random_state=SEED, loss="absolute_error")


# --------------------------------------------------------------------------- #
# Baselines
# --------------------------------------------------------------------------- #


def _train_mean(train: Sequence[Row]) -> float:
    return float(np.mean([r.target for r in train])) if train else 0.0


def _train_median(train: Sequence[Row]) -> float:
    return float(np.median([r.target for r in train])) if train else 0.0


INVOICE_CLS_BASELINES = [
    BaselineSpec("Customer's average days late", lambda tr, r: r.features["avg_days_late"], primary=True),
    BaselineSpec("Credit score (fixed weights)", lambda tr, r: 100.0 - r.features["score"]),
    BaselineSpec("Overall late rate", lambda tr, r: _train_mean(tr), is_probability=True),
]
INVOICE_REG_BASELINES = [
    BaselineSpec("Customer's average days late", lambda tr, r: r.features["avg_days_late"] if r.features["observations"] > 0 else _train_median(tr), primary=True),
    BaselineSpec("Overall median", lambda tr, r: _train_median(tr)),
]
BILL_BASELINES = [
    BaselineSpec("Vendor's average days late", lambda tr, r: r.features["vendor_mean_lag"] if r.features["vendor_prior_n"] > 0 else _train_median(tr), primary=True),
    BaselineSpec("Overall median", lambda tr, r: _train_median(tr)),
]
LEARNED_BASELINES = [BaselineSpec("Fixed-weight score (today)", lambda tr, r: 100.0 - r.features["score"], primary=True)]


# --------------------------------------------------------------------------- #
# Task definitions
# --------------------------------------------------------------------------- #

TASKS: Dict[str, Dict[str, Any]] = {
    "invoice_late": {
        "title": "Will this invoice be paid late?",
        "description": "Probability that each invoice is paid more than 10 days after its due date, from the customer's payment history and the invoice itself.",
        "feeds": "Receivables and the credit score",
        "models": [
            ModelSpec("logistic", logistic, INVOICE_FEATURES, "Logistic regression"),
            ModelSpec("gbm", gbm_classifier, INVOICE_FEATURES, "Gradient boosting"),
        ],
        "baselines": INVOICE_CLS_BASELINES,
    },
    "invoice_days_late": {
        "title": "How many days late will this invoice be paid?",
        "description": "Expected days between the due date and payment for each invoice.",
        "feeds": "Receivables timing",
        "models": [
            ModelSpec("ridge", ridge, INVOICE_FEATURES, "Ridge regression"),
            ModelSpec("gbm", gbm_regressor, INVOICE_FEATURES, "Gradient boosting"),
        ],
        "baselines": INVOICE_REG_BASELINES,
    },
    "learned_credit_score": {
        "title": "Learned credit-score weights",
        "description": "Learns how much each ingredient of the credit score should count, from what customers actually did, instead of using hand-set weights.",
        "feeds": "Credit score",
        "models": [ModelSpec("learned_weights", logistic, COMPONENT_FEATURES, "Logistic regression on the five ingredients")],
        "baselines": LEARNED_BASELINES,
    },
    "bill_days_late": {
        "title": "When will this vendor bill actually be paid?",
        "description": "Expected days between the due date and payment for each vendor bill.",
        "feeds": "Payables timing",
        "models": [
            ModelSpec("ridge", ridge, BILL_FEATURES, "Ridge regression"),
            ModelSpec("gbm", gbm_regressor, BILL_FEATURES, "Gradient boosting"),
        ],
        "baselines": BILL_BASELINES,
    },
}
