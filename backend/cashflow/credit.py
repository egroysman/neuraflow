"""Payment-behavior credit score for each customer, and a back-test of it.

The score (0-100, higher is safer) is built only from how a customer has paid
invoices: how late, how often, how consistently, whether they are getting
slower, and what is past due right now. It never looks at a label, industry or
anything outside the invoice history.

``score_customers`` scores as of a date using only what was known on that date.
``backtest`` replays that at many past dates and checks the score against what
those customers actually did next, so the claim "this score predicts late
payment" is measured rather than assumed.
"""
from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from typing import Any, Dict, List, Optional, Sequence, Tuple

from .ar import Invoice

HALF_LIFE_DAYS = 90.0  # a payment 90 days ago counts half as much as one today
LATE_RATE_DAYS = 5  # "late" for the late-rate component
PRIOR_SCORE = 50.0  # what a customer with no history is assumed to be
PRIOR_STRENGTH = 4.0  # history worth this many payments pulls the score halfway off the prior
WEIGHTS = {"timing": 0.40, "late_rate": 0.30, "open_exposure": 0.15, "consistency": 0.05, "trend": 0.10}
LABELS = {
    "timing": "How late they pay",
    "late_rate": "How often they pay late",
    "open_exposure": "What is past due now",
    "consistency": "How predictable they are",
    "trend": "Getting faster or slower",
}
BANDS = [("Low risk", 70.0), ("Watch", 40.0), ("High risk", -1.0)]


def band_for(score: float) -> str:
    for name, floor in BANDS:
        if score >= floor:
            return name
    return BANDS[-1][0]


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _wmean(values: Sequence[float], weights: Sequence[float]) -> float:
    total = sum(weights)
    return sum(v * w for v, w in zip(values, weights)) / total if total else 0.0


def _wstd(values: Sequence[float], weights: Sequence[float]) -> float:
    total = sum(weights)
    if total <= 0 or len(values) < 2:
        return 0.0
    m = _wmean(values, weights)
    return math.sqrt(sum(w * (v - m) ** 2 for v, w in zip(values, weights)) / total)


def _observations(invoices: Sequence[Invoice], as_of: dt.date) -> List[Tuple[dt.date, float]]:
    """(when we learned it, days late) for every payment made, plus invoices already past due and unpaid."""
    obs: List[Tuple[dt.date, float]] = []
    for inv in invoices:
        if inv.invoice_date > as_of:
            continue
        if inv.payment_date is not None and inv.payment_date <= as_of:
            obs.append((inv.payment_date, float((inv.payment_date - inv.due_date).days)))
        elif inv.due_date < as_of:
            # Still unpaid: it is at least this late today (a lower bound, never an overstatement).
            obs.append((as_of, float((as_of - inv.due_date).days)))
    return obs


def score_customer(invoices: Sequence[Invoice], as_of: dt.date) -> Dict[str, Any]:
    """Score one customer from their invoices, using only what was known on ``as_of``."""
    obs = _observations(invoices, as_of)
    days = [max(-10.0, min(120.0, d)) for _, d in obs]
    weights = [0.5 ** (max(0, (as_of - when).days) / HALF_LIFE_DAYS) for when, _ in obs]
    paid_n = sum(1 for i in invoices if i.payment_date is not None and i.payment_date <= as_of and i.invoice_date <= as_of)

    avg_late = _wmean(days, weights) if days else 0.0
    late_share = _wmean([1.0 if d > LATE_RATE_DAYS else 0.0 for d in days], weights) if days else 0.0
    spread = _wstd(days, weights)

    recent = [d for (w, d) in obs if 0 <= (as_of - w).days < 90]
    prior = [d for (w, d) in obs if 90 <= (as_of - w).days < 180]
    trend_days: Optional[float] = None
    if len(recent) >= 2 and len(prior) >= 2:
        trend_days = sum(recent) / len(recent) - sum(prior) / len(prior)

    open_inv = [i for i in invoices if i.invoice_date <= as_of and (i.payment_date is None or i.payment_date > as_of)]
    open_total = sum(i.open_amount or i.amount for i in open_inv)
    past_due = [i for i in open_inv if i.due_date < as_of]
    past_due_amt = sum(i.open_amount or i.amount for i in past_due)
    oldest = max(((as_of - i.due_date).days for i in past_due), default=0)
    pd_share = past_due_amt / open_total if open_total else 0.0

    sub = {
        "timing": 100.0 * (1.0 - _clamp(avg_late / 45.0)),
        "late_rate": 100.0 * (1.0 - late_share),
        "open_exposure": 100.0 * (1.0 - 0.5 * _clamp(pd_share) - 0.5 * _clamp(oldest / 60.0)),
        "consistency": 100.0 * (1.0 - _clamp(spread / 20.0)),
        "trend": 50.0 if trend_days is None else 50.0 - 50.0 * _clamp(trend_days / 20.0, -1.0, 1.0),
    }
    raw = sum(WEIGHTS[k] * sub[k] for k in WEIGHTS)
    n = len(obs)
    pull = n / (n + PRIOR_STRENGTH)
    score = pull * raw + (1.0 - pull) * PRIOR_SCORE
    confidence = "high" if n >= 12 else "medium" if n >= 5 else "low"

    reasons: List[str] = []
    if n:
        reasons.append(
            f"Pays about {abs(avg_late):.0f} days {'late' if avg_late > 0.5 else 'early'} on average, counting recent payments most."
            if abs(avg_late) >= 0.5
            else "Pays on the due date on average, counting recent payments most."
        )
        reasons.append(f"{late_share * 100:.0f}% of invoices were paid more than {LATE_RATE_DAYS} days late.")
    if trend_days is not None and abs(trend_days) >= 3:
        reasons.append(
            f"Getting slower: paying {trend_days:.0f} days later than in the 90 days before." if trend_days > 0
            else f"Getting faster: paying {abs(trend_days):.0f} days sooner than in the 90 days before."
        )
    if past_due:
        reasons.append(f"{len(past_due)} open invoice{'s' if len(past_due) != 1 else ''} past due (${past_due_amt:,.0f}), the oldest {oldest} days.")
    if confidence == "low":
        reasons.append(f"Only {n} payment{'s' if n != 1 else ''} on record, so the score leans toward average.")

    return {
        "score": round(score, 1),
        "band": band_for(score),
        "confidence": confidence,
        "observations": n,
        "paid_invoices": paid_n,
        "components": [
            {"key": k, "label": LABELS[k], "score": round(sub[k], 1), "weight": WEIGHTS[k]} for k in WEIGHTS
        ],
        "avg_days_late": round(avg_late, 1),
        "late_rate_pct": round(late_share * 100, 1),
        "spread_days": round(spread, 1),
        "trend_days": None if trend_days is None else round(trend_days, 1),
        "open_amount": round(open_total, 2),
        "past_due_amount": round(past_due_amt, 2),
        "oldest_days_past_due": oldest,
        "reasons": reasons,
    }


def score_customers(invoices: Sequence[Invoice], as_of: dt.date) -> List[Dict[str, Any]]:
    by_customer: Dict[str, List[Invoice]] = defaultdict(list)
    for inv in invoices:
        by_customer[inv.customer_id].append(inv)
    rows = []
    for cust, items in by_customer.items():
        if not any(i.invoice_date <= as_of for i in items):
            continue
        rows.append({"customer_id": cust, **score_customer(items, as_of)})
    rows.sort(key=lambda r: (r["score"], r["customer_id"]))
    return rows


def portfolio_summary(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {name: 0 for name, _ in BANDS}
    open_by = {name: 0.0 for name, _ in BANDS}
    for r in rows:
        counts[r["band"]] += 1
        open_by[r["band"]] += r["open_amount"]
    total_open = sum(open_by.values())
    return {
        "customers": len(rows),
        "bands": [
            {"band": name, "customers": counts[name], "open_amount": round(open_by[name], 2),
             "open_share_pct": round(open_by[name] / total_open * 100, 1) if total_open else 0.0}
            for name, _ in BANDS
        ],
        "average_score": round(sum(r["score"] for r in rows) / len(rows), 1) if rows else None,
        "open_amount": round(total_open, 2),
    }


# --------------------------------------------------------------------------- #
# Back-test
# --------------------------------------------------------------------------- #

BAND_INDEX = {name: i for i, (name, _) in enumerate(BANDS)}
MIN_HISTORY = 3  # a customer needs this many observations before a cutoff to be evaluated
BOOTSTRAPS = 400


def _auc(labels: Sequence[int], risk: Sequence[float]) -> Optional[float]:
    """Chance a random late invoice has a higher risk than a random on-time one (ties count half)."""
    import numpy as np
    from scipy.stats import rankdata

    y = np.asarray(labels, dtype=int)
    pos = int(y.sum())
    neg = len(y) - pos
    if pos == 0 or neg == 0:
        return None
    ranks = rankdata(np.asarray(risk, dtype=float))
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def _percentile(values: List[float], q: float) -> float:
    values = sorted(values)
    if not values:
        return float("nan")
    k = (len(values) - 1) * q
    lo, hi = int(math.floor(k)), int(math.ceil(k))
    return values[lo] + (values[hi] - values[lo]) * (k - lo)


def _naive_risk(invoices: Sequence[Invoice], as_of: dt.date, kind: str) -> Optional[float]:
    paid = sorted(
        ((i.payment_date, (i.payment_date - i.due_date).days) for i in invoices
         if i.payment_date is not None and i.payment_date <= as_of and i.invoice_date <= as_of)
    )
    if not paid:
        return None
    return float(paid[-1][1]) if kind == "last" else sum(d for _, d in paid) / len(paid)


def build_records(
    invoices: Sequence[Invoice],
    horizon_days: int = 90,
    late_days: int = 10,
    step_days: int = 14,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """One record per invoice due in the window after each cutoff, scored with data known at the cutoff."""
    paid_dates = [i.payment_date for i in invoices if i.payment_date]
    if not invoices or not paid_dates:
        return [], {}
    data_end = max(paid_dates)
    first = min(i.invoice_date for i in invoices)
    by_customer: Dict[str, List[Invoice]] = defaultdict(list)
    for inv in invoices:
        by_customer[inv.customer_id].append(inv)

    cutoffs: List[dt.date] = []
    t = first + dt.timedelta(days=90)
    while t + dt.timedelta(days=horizon_days) <= data_end:
        cutoffs.append(t)
        t += dt.timedelta(days=step_days)

    records: List[Dict[str, Any]] = []
    censored = 0
    thin = 0
    for T in cutoffs:
        end = T + dt.timedelta(days=horizon_days)
        for cust, items in by_customer.items():
            window = [i for i in items if T < i.due_date <= end and (i.payment_date is None or i.payment_date > T)]
            if not window:
                continue
            s = score_customer(items, T)
            if s["observations"] < MIN_HISTORY:
                thin += len(window)
                continue
            last = _naive_risk(items, T, "last")
            mean_all = _naive_risk(items, T, "mean")
            for inv in window:
                if inv.payment_date is not None:
                    late = (inv.payment_date - inv.due_date).days > late_days
                elif (data_end - inv.due_date).days > late_days:
                    late = True
                else:
                    censored += 1  # unpaid but not yet old enough to call late
                    continue
                records.append(
                    {
                        "cutoff": T, "customer_id": cust, "invoice_id": inv.invoice_id, "amount": inv.amount,
                        "due_date": inv.due_date, "score": s["score"], "band": s["band"],
                        "confidence": s["confidence"], "late": int(late),
                        "naive_last": last, "naive_mean": mean_all,
                        "components": {c["key"]: c["score"] for c in s["components"]},
                    }
                )
    meta = {
        "cutoffs": cutoffs, "data_end": data_end, "first_invoice": first,
        "censored_excluded": censored, "thin_history_excluded": thin,
    }
    return records, meta


def _band_stats(recs: List[Dict[str, Any]], base_rate: float) -> List[Dict[str, Any]]:
    out = []
    total_late = sum(r["late"] for r in recs)
    total_late_amt = sum(r["amount"] for r in recs if r["late"])
    for name, _ in BANDS:
        sub = [r for r in recs if r["band"] == name]
        late = sum(r["late"] for r in sub)
        out.append(
            {
                "band": name, "invoices": len(sub), "customers": len({r["customer_id"] for r in sub}),
                "late_invoices": late, "late_rate": (late / len(sub)) if sub else None,
                "lift": ((late / len(sub)) / base_rate) if sub and base_rate else None,
                "share_of_late_invoices": (late / total_late) if total_late else None,
                "share_of_late_dollars": (sum(r["amount"] for r in sub if r["late"]) / total_late_amt) if total_late_amt else None,
            }
        )
    return out


def _findings(auc: Optional[float], baselines: List[Dict[str, Any]], components: List[Dict[str, Any]], bands: List[Dict[str, Any]]) -> List[str]:
    """Plain statements generated from the measured results, so they cannot drift from the numbers."""
    out: List[str] = []
    if auc is not None:
        out.append(f"The score ranks a late invoice as riskier than an on-time one {auc * 100:.0f}% of the time.")
    best = max((b for b in baselines if b["auc"] is not None), key=lambda b: b["auc"], default=None)
    if best and auc is not None:
        diff = (auc - best["auc"]) * 100
        if diff >= 2:
            out.append(f"That beats the simple rule \"{best['name'].lower()}\" ({best['auc'] * 100:.0f}%) by {diff:.0f} points.")
        elif diff <= -2:
            out.append(f"The simple rule \"{best['name'].lower()}\" does better ({best['auc'] * 100:.0f}%), so on this data the extra ingredients are not adding value yet.")
        else:
            out.append(f"That is about the same as the simple rule \"{best['name'].lower()}\" ({best['auc'] * 100:.0f}%).")
    strong = [c["label"].lower() for c in components if c["auc"] is not None and c["auc"] >= 0.65]
    flat = [c["label"].lower() for c in components if c["auc"] is not None and 0.45 <= c["auc"] <= 0.55]
    wrong = [c["label"].lower() for c in components if c["auc"] is not None and c["auc"] < 0.45]
    if strong:
        out.append("Carrying the signal: " + ", ".join(strong) + ".")
    if flat or wrong:
        out.append("Showing no useful signal here: " + ", ".join(flat + wrong) + ". Re-weight them once real customer data is loaded.")
    high = next((b for b in bands if b["band"] == "High risk" and b["late_rate"] is not None), None)
    low = next((b for b in bands if b["band"] == "Low risk" and b["late_rate"] is not None), None)
    if high and low:
        out.append(f"{high['late_rate'] * 100:.0f}% of invoices from High risk customers were late, versus {low['late_rate'] * 100:.0f}% from Low risk customers.")
    return out


def backtest(
    invoices: Sequence[Invoice],
    horizon_days: int = 90,
    late_days: int = 10,
    step_days: int = 14,
    seed: int = 7,
) -> Dict[str, Any]:
    import random

    records, meta = build_records(invoices, horizon_days, late_days, step_days)
    params = {"horizon_days": horizon_days, "late_days": late_days, "step_days": step_days, "min_history": MIN_HISTORY}
    if not records:
        return {"available": False, "params": params, "reason": "Not enough payment history to test the score yet."}

    labels = [r["late"] for r in records]
    risk = [100.0 - r["score"] for r in records]
    n_late = sum(labels)
    base = n_late / len(records)
    auc = _auc(labels, risk)

    import numpy as np

    by_cust: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for r in records:
        by_cust[r["customer_id"]].append(r)
    cust_ids = sorted(by_cust)
    arrays = {
        c: (
            np.array([r["late"] for r in by_cust[c]]),
            np.array([100.0 - r["score"] for r in by_cust[c]]),
            np.array([BAND_INDEX[r["band"]] for r in by_cust[c]]),
        )
        for c in cust_ids
    }
    rng = random.Random(seed)
    auc_reps: List[float] = []
    band_reps: Dict[str, List[float]] = {name: [] for name, _ in BANDS}
    for _ in range(BOOTSTRAPS):  # resample whole customers: a customer's invoices are not independent
        picks = [arrays[rng.choice(cust_ids)] for _ in cust_ids]
        yl = np.concatenate([p[0] for p in picks])
        rk = np.concatenate([p[1] for p in picks])
        bd = np.concatenate([p[2] for p in picks])
        a = _auc(yl, rk)
        if a is not None:
            auc_reps.append(a)
        for name, idx in BAND_INDEX.items():
            m = bd == idx
            if m.any():
                band_reps[name].append(float(yl[m].mean()))

    bands = _band_stats(records, base)
    for b in bands:
        reps = band_reps[b["band"]]
        b["ci_low"] = _percentile(reps, 0.025) if len(reps) >= 20 else None
        b["ci_high"] = _percentile(reps, 0.975) if len(reps) >= 20 else None

    ordered = sorted(records, key=lambda r: r["score"])
    k = 5
    calibration = []
    for q in range(k):
        chunk = ordered[q * len(ordered) // k: (q + 1) * len(ordered) // k]
        if chunk:
            calibration.append(
                {"group": q + 1, "invoices": len(chunk), "score_low": min(r["score"] for r in chunk),
                 "score_high": max(r["score"] for r in chunk), "avg_score": sum(r["score"] for r in chunk) / len(chunk),
                 "late_rate": sum(r["late"] for r in chunk) / len(chunk)}
            )

    by_cutoff = []
    for T in meta["cutoffs"]:
        sub = [r for r in records if r["cutoff"] == T]
        if sub:
            by_cutoff.append(
                {"cutoff": T, "invoices": len(sub), "late_rate": sum(r["late"] for r in sub) / len(sub),
                 "auc": _auc([r["late"] for r in sub], [100.0 - r["score"] for r in sub])}
            )

    baselines = []
    for key, name in (("naive_mean", "Average days late over all history"), ("naive_last", "How late the last payment was")):
        sub = [r for r in records if r[key] is not None]
        baselines.append({"name": name, "auc": _auc([r["late"] for r in sub], [r[key] for r in sub]) if sub else None})

    components = []
    for key in WEIGHTS:
        components.append(
            {"key": key, "label": LABELS[key], "weight": WEIGHTS[key],
             "auc": _auc(labels, [100.0 - r["components"][key] for r in records])}
        )
    findings = _findings(auc, baselines, components, bands)
    high = next(b for b in bands if b["band"] == "High risk")
    low = next(b for b in bands if b["band"] == "Low risk")
    return {
        "available": True,
        "params": params,
        "data": {
            "first_invoice": meta["first_invoice"], "data_end": meta["data_end"], "cutoffs": len(meta["cutoffs"]),
            "first_cutoff": meta["cutoffs"][0], "last_cutoff": meta["cutoffs"][-1],
        },
        "sample": {
            "invoices": len(records), "customers": len(cust_ids), "late_invoices": n_late, "base_late_rate": base,
            "censored_excluded": meta["censored_excluded"], "thin_history_excluded": meta["thin_history_excluded"],
        },
        "auc": {
            "value": auc,
            "ci_low": _percentile(auc_reps, 0.025) if auc_reps else None,
            "ci_high": _percentile(auc_reps, 0.975) if auc_reps else None,
        },
        "baselines": baselines,
        "components": components,
        "findings": findings,
        "bands": bands,
        "calibration": calibration,
        "by_cutoff": by_cutoff,
        "headline": {
            "high_risk_late_rate": high["late_rate"], "low_risk_late_rate": low["late_rate"],
            "base_late_rate": base,
        },
        "method": [
            f"Replayed the score at {len(meta['cutoffs'])} past dates, {step_days} days apart. At each date it used only payments and invoices known on that date.",
            f"For every invoice that fell due in the next {horizon_days} days and was not yet paid, we checked what happened: late means paid more than {late_days} days after the due date, or still unpaid that long after.",
            "Invoices too recent to judge (unpaid but not yet old enough to be late) are left out, and so are customers with fewer than "
            f"{MIN_HISTORY} payments on record at that date.",
            "AUC is the chance that a randomly chosen late invoice came from a customer with a worse score than a randomly chosen on-time one (0.5 is a coin flip, 1.0 is perfect).",
            "Confidence ranges come from re-sampling whole customers 400 times, because one customer's invoices are not independent of each other.",
            "Windows overlap, so the same invoice can appear at more than one date; the customer-level resampling accounts for that.",
        ],
        "records": records,
    }


def records_csv(result: Dict[str, Any]) -> str:
    import csv
    import io

    buf = io.StringIO()
    cols = ["cutoff", "customer_id", "invoice_id", "due_date", "amount", "score", "band", "confidence", "late"]
    w = csv.writer(buf)
    w.writerow(cols)
    for r in result.get("records", []):
        w.writerow([r[c].isoformat() if isinstance(r[c], dt.date) else r[c] for c in cols])
    return buf.getvalue()
