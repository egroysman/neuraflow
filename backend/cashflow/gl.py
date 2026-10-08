"""General ledger: trial balance, monthly actuals, forecast baselines and tie-outs.

The bundled sample ledger is generated from the same invoices, bills and payroll
roster as the rest of the model, so the ledger's receivables and payables equal
the sub-ledgers. Account "model lines" map ledger accounts onto the forecast's
revenue, cost of sales, payroll, operating expense, depreciation and interest.
"""
from __future__ import annotations

import csv
import datetime as dt
import os
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent.parent
PL_LINES = ["revenue", "cogs", "payroll", "opex", "depreciation", "interest"]


def _read(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def load_gl() -> Optional[Dict[str, Any]]:
    """Accounts and journal lines from the bundled sample (or env override paths)."""
    acc_env, jr_env = os.getenv("DEFAULT_GL_ACCOUNTS_CSV_PATH"), os.getenv("DEFAULT_GL_JOURNAL_CSV_PATH")
    acc = Path(acc_env) if acc_env and Path(acc_env).exists() else HERE / "neuraflow_gl_accounts.csv"
    jr = Path(jr_env) if jr_env and Path(jr_env).exists() else HERE / "neuraflow_gl_journal.csv"
    accounts, journal = _read(acc), _read(jr)
    if not accounts or not journal:
        return None
    return {"accounts": accounts, "journal": journal}


def load_payroll_rows() -> List[Dict[str, Any]]:
    env = os.getenv("DEFAULT_PAYROLL_CSV_PATH")
    path = Path(env) if env and Path(env).exists() else HERE / "neuraflow_payroll.csv"
    return _read(path)


def _d(s: str) -> dt.date:
    return dt.date.fromisoformat(s[:10])


def _f(x: Any) -> float:
    try:
        return float(x or 0)
    except (TypeError, ValueError):
        return 0.0


def _ym(d: dt.date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _month_end(d: dt.date) -> dt.date:
    nxt = dt.date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def _line_of(model_line: str) -> str:
    return model_line.split(":", 1)[0]


def prepare(gl: Dict[str, Any]) -> Dict[str, Any]:
    acc = {a["AccountID"]: a for a in gl["accounts"]}
    lines = []
    for r in gl["journal"]:
        if r["AccountID"] not in acc:
            continue
        lines.append({"entry": r["EntryID"], "date": _d(r["Date"]), "account": r["AccountID"],
                      "debit": _f(r["Debit"]), "credit": _f(r["Credit"]), "memo": r.get("Memo", ""), "source": r.get("Source", "")})
    return {"acc": acc, "lines": lines}


def trial_balance(p: Dict[str, Any], as_of: dt.date) -> Dict[str, Any]:
    dr: Dict[str, float] = defaultdict(float)
    cr: Dict[str, float] = defaultdict(float)
    for ln in p["lines"]:
        if ln["date"] <= as_of:
            dr[ln["account"]] += ln["debit"]
            cr[ln["account"]] += ln["credit"]
    rows = []
    for aid, a in sorted(p["acc"].items()):
        bal = dr[aid] - cr[aid]
        rows.append({"account_id": aid, "name": a["AccountName"], "type": a["AccountType"], "subtype": a["Subtype"],
                     "debit": dr[aid], "credit": cr[aid], "balance": bal,
                     "debit_balance": max(bal, 0.0), "credit_balance": max(-bal, 0.0)})
    td, tc = sum(r["debit_balance"] for r in rows), sum(r["credit_balance"] for r in rows)
    return {"rows": rows, "total_debit": td, "total_credit": tc, "balanced": abs(td - tc) < 0.5}


def monthly_actuals(p: Dict[str, Any], as_of: dt.date) -> List[Dict[str, Any]]:
    """P&L by calendar month, from the ledger. The month containing ``as_of`` is partial unless it is a month end."""
    buckets: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    opex_names: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))
    for ln in p["lines"]:
        a = p["acc"][ln["account"]]
        if a["AccountType"] not in ("Revenue", "Expense") or ln["date"] > as_of:
            continue
        net = ln["credit"] - ln["debit"] if a["AccountType"] == "Revenue" else ln["debit"] - ln["credit"]
        ml = a["ModelLine"]
        key = _line_of(ml)
        ym = _ym(ln["date"])
        buckets[ym][key] += net
        if key == "opex":
            opex_names[ym][ml.split(":", 1)[1]] += net
    out = []
    for ym in sorted(buckets):
        y, m = int(ym[:4]), int(ym[5:])
        start = dt.date(y, m, 1)
        row = {k: buckets[ym].get(k, 0.0) for k in PL_LINES}
        row["opex_lines"] = dict(opex_names[ym])
        row["pretax_profit"] = row["revenue"] - sum(row[k] for k in PL_LINES if k != "revenue")
        row["month"] = ym
        row["label"] = start.strftime("%b %Y")
        row["partial"] = _month_end(start) > as_of
        out.append(row)
    return out


def _complete(months: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [m for m in months if not m["partial"]]


def baselines(p: Dict[str, Any], as_of: dt.date, months: Optional[List[Dict[str, Any]]] = None) -> Optional[Dict[str, Any]]:
    """Forecast starting points taken from the last three complete months and the balances at ``as_of``."""
    months = months if months is not None else monthly_actuals(p, as_of)
    last = _complete(months)[-3:]
    if not last:
        return None
    n = len(last)
    avg = lambda f: sum(f(m) for m in last) / n  # noqa: E731
    revenue = avg(lambda m: m["revenue"])
    opex: Dict[str, float] = defaultdict(float)
    for m in last:
        for k, v in m["opex_lines"].items():
            opex[k] += v / n
    tb = {r["account_id"]: r["balance"] for r in trial_balance(p, as_of)["rows"]}
    by_line: Dict[str, float] = defaultdict(float)
    for aid, bal in tb.items():
        by_line[_line_of(p["acc"][aid]["ModelLine"])] += bal
    # term loan: balance, payment and implied rate from the most recent payment entries
    loan = None
    loan_accts = [aid for aid, a in p["acc"].items() if a["ModelLine"] == "debt"]
    if loan_accts:
        pays = sorted({ln["date"] for ln in p["lines"] if ln["account"] in loan_accts and ln["debit"] > 0 and ln["date"] <= as_of})
        if pays:
            last_pay = pays[-1]
            principal = sum(ln["debit"] for ln in p["lines"] if ln["account"] in loan_accts and ln["date"] == last_pay)
            interest = sum(ln["debit"] for ln in p["lines"] if p["acc"][ln["account"]]["ModelLine"] == "interest" and ln["date"] == last_pay)
            bal = -sum(tb[a] for a in loan_accts)
            prior = bal + principal
            loan = {"balance": bal, "monthly_payment": principal + interest,
                    "annual_rate_pct": (interest * 12.0 / prior * 100.0) if prior > 0 else 0.0}
    return {
        "window_months": [m["month"] for m in last],
        "monthly_revenue": revenue,
        "cogs_pct": (avg(lambda m: m["cogs"]) / revenue * 100.0) if revenue else 0.0,
        "payroll_monthly": avg(lambda m: m["payroll"]),
        "opex_monthly": dict(opex),
        "depreciation_monthly": avg(lambda m: m["depreciation"]),
        "starting_cash": by_line.get("cash", 0.0),
        "receivables": by_line.get("ar", 0.0),
        "payables": -by_line.get("ap", 0.0),
        "ppe_net": by_line.get("ppe", 0.0),
        "loan": loan,
    }


def tie_out(p: Dict[str, Any], as_of: dt.date, invoices: List[Any], bills: List[Any], months: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ledger vs sub-ledger checks. Each row: label, ledger, source, difference, ok."""
    bl = baselines(p, as_of, months) or {}
    unpaid = lambda x: x.payment_date is None or x.payment_date > as_of  # noqa: E731
    inv_open = sum(i.amount for i in invoices if i.invoice_date <= as_of and unpaid(i))
    bill_open = sum(b.amount for b in bills if b.bill_date <= as_of and unpaid(b))
    inv_rev = sum(getattr(i, "amount", 0.0) for i in invoices if getattr(i, "invoice_date", as_of) <= as_of)
    gl_rev = sum(m["revenue"] for m in months)
    gl_cogs_opex = sum(m["cogs"] + m["opex"] for m in months)
    bill_total = sum(getattr(b, "amount", 0.0) for b in bills if getattr(b, "bill_date", as_of) <= as_of)
    rows = [
        ("Accounts receivable vs open invoices", bl.get("receivables", 0.0), inv_open),
        ("Accounts payable vs open vendor bills", bl.get("payables", 0.0), bill_open),
        ("Revenue vs invoices issued", gl_rev, inv_rev),
        ("Vendor costs vs bills received", gl_cogs_opex, bill_total),
    ]
    return [{"label": a, "ledger": b, "source": c, "difference": b - c, "ok": abs(b - c) <= max(1.0, abs(c) * 0.001)} for a, b, c in rows]


def _fc_month(row: Dict[str, Any]) -> str:
    """Calendar month a forecast window mostly falls in (its midpoint)."""
    mid = row["start"] + (row["end"] - row["start"]) / 2
    return _ym(mid)


def compare(p: Dict[str, Any], as_of: dt.date, pnl: List[Dict[str, Any]], months: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Actuals next to the forecast: a timeline, a baseline check and variance for any overlapping months.

    The baseline check uses only what was known at ``as_of``; the timeline and
    variance use every complete month in the ledger, so moving the start date
    back shows how the forecast would have compared with what really happened.
    """
    ledger_end = max(ln["date"] for ln in p["lines"])
    known = months if months is not None else monthly_actuals(p, as_of)
    every = _complete(monthly_actuals(p, ledger_end))
    bl = baselines(p, as_of, known)
    fc_cost = lambda r: r["cogs"] + r["payroll"] + r["opex"] + r["depreciation"] + r["interest"]  # noqa: E731
    actual_ym = {m["month"]: m for m in every}

    rows: Dict[str, Dict[str, Any]] = {}
    for m in every:
        rows[m["month"]] = {"label": m["label"], "actual_revenue": m["revenue"], "actual_costs": m["revenue"] - m["pretax_profit"],
                            "actual_pretax": m["pretax_profit"], "forecast_revenue": None, "forecast_costs": None, "forecast_pretax": None}
    for r in pnl:
        key = _fc_month(r)
        while key in rows and rows[key]["forecast_revenue"] is not None:
            key += "+"
        row = rows.setdefault(key, {"label": r["label"], "actual_revenue": None, "actual_costs": None, "actual_pretax": None})
        row.update({"forecast_revenue": r["revenue"], "forecast_costs": fc_cost(r), "forecast_pretax": r["pretax_profit"]})
    ordered = [rows[k] for k in sorted(rows)]
    first_fc = next((i for i, r in enumerate(ordered) if r["forecast_revenue"] is not None), 0)
    timeline = ordered[max(0, first_fc - 12):]

    check = []
    if bl and pnl:
        first = pnl[0]
        pairs = [
            ("Revenue", bl["monthly_revenue"], first["revenue"]),
            ("Cost of sales", bl["monthly_revenue"] * bl["cogs_pct"] / 100.0, first["cogs"]),
            ("Payroll", bl["payroll_monthly"], first["payroll"]),
            ("Operating expenses", sum(bl["opex_monthly"].values()), first["opex"]),
            ("Depreciation", bl["depreciation_monthly"], first["depreciation"]),
        ]
        for label, actual, fc in pairs:
            diff = fc - actual
            check.append({"label": label, "actual_avg": actual, "forecast_first_month": fc, "difference": diff,
                          "difference_pct": (diff / actual * 100.0) if actual else None})

    variance = []
    for r in pnl:
        ym = _fc_month(r)
        if ym in actual_ym:
            a = actual_ym[ym]
            variance.append({"label": a["label"], "approximate": as_of.day != 1,
                             "lines": [{"label": lab, "actual": a[k], "forecast": r[k], "variance": a[k] - r[k]}
                                       for lab, k in (("Revenue", "revenue"), ("Cost of sales", "cogs"), ("Payroll", "payroll"),
                                                      ("Operating expenses", "opex"), ("Depreciation", "depreciation"), ("Interest", "interest"))]})
    return {"timeline": timeline, "baseline_check": check, "variance": variance,
            "baseline_window": bl["window_months"] if bl else [], "history_months": len(every)}


def overview(as_of: Optional[dt.date], invoices: List[Any], bills: List[Any]) -> Optional[Dict[str, Any]]:
    """Payload for GET /cashflow/gl."""
    gl = load_gl()
    if not gl:
        return None
    p = prepare(gl)
    last = max(ln["date"] for ln in p["lines"])
    when = as_of or last
    months = monthly_actuals(p, when)
    return {
        "as_of": when,
        "first_date": min(ln["date"] for ln in p["lines"]),
        "last_date": last,
        "entry_count": len({ln["entry"] for ln in p["lines"]}),
        "line_count": len(p["lines"]),
        "accounts": [{"account_id": a["AccountID"], "name": a["AccountName"], "type": a["AccountType"],
                      "subtype": a["Subtype"], "model_line": a["ModelLine"]} for a in gl["accounts"]],
        "trial_balance": trial_balance(p, when),
        "monthly": months,
        "baselines": baselines(p, when, months),
        "tie_out": tie_out(p, when, invoices, bills, months),
        "recent_entries": [
            {"entry": ln["entry"], "date": ln["date"], "account": ln["account"], "debit": ln["debit"],
             "credit": ln["credit"], "memo": ln["memo"], "source": ln["source"]}
            for ln in sorted(p["lines"], key=lambda x: (x["date"], x["entry"]))[-40:]
        ],
    }
