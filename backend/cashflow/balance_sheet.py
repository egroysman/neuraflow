"""Projected balance sheet that balances by construction.

Opening position: cash = starting cash, receivables = open invoices, payables =
open vendor bills (or the lump), PP&E = opening net book value, debt = loan
balances; equity is the balancing figure. Each month then rolls forward from the
same events and P&L the cash flow uses:

  receivables  += revenue billed - collections
  PP&E         += additions (incl. financed) - depreciation (+ other investing)
  payables     += cost of sales accrued - vendor and open-bill payments
  accrued pay  += payroll cost - payroll cash (pay-run timing, benefits)
  taxes payable += tax accrued at quarter end - tax paid
  debt         += financed capex - principal paid (debt service - interest)
  equity       += net income + other operating + other financing

so the ``check`` row (assets - liabilities - equity) stays at zero. Receivables
not expected to be collected stay in the balance and are shown as a memo.
"""
from __future__ import annotations

from typing import Any, Dict, List


def build(run: Any) -> Dict[str, Any]:
    a, adj, ex = run.assumptions, run.adjustments, run.extras
    n = a.general.horizon_months
    pnl, monthly = run.pnl, run.monthly
    tax_exp: List[float] = ex.get("tax_expense") or [0.0] * n
    plan_m = ex["capex"]["monthly"]
    bills = ex.get("projected_bills") or []

    ar0 = sum(p["open_amount"] for p in run.projected_ar)
    ap0 = sum(b["open_amount"] for b in bills) if bills else a.costs.opening_ap
    debt0 = sum(l.balance for l in a.loans)
    ppe0 = a.capex.opening_ppe_net
    cash0 = a.general.starting_cash + adj.starting_cash_change
    acc0 = ((ex.get("payroll") or {}).get("opening_accrued", 0.0)) if ex.get("payroll") else 0.0
    eq0 = cash0 + ar0 + ppe0 - ap0 - debt0 - acc0

    def row(label, cash, ar, ppe, ap, acc, tax, debt, eq):
        assets = cash + ar + ppe
        liab = ap + acc + tax + debt
        return {
            "label": label, "cash": cash, "receivables": ar, "ppe_net": ppe, "total_assets": assets,
            "payables": ap, "accrued_payroll": acc, "taxes_payable": tax, "debt": debt, "total_liabilities": liab,
            "equity": eq, "total_liabilities_equity": liab + eq, "check": assets - liab - eq,
            "working_capital": cash + ar - ap - acc - tax, "net_debt": debt - cash,
        }

    opening = row("Opening", cash0, ar0, ppe0, ap0, acc0, 0.0, debt0, eq0)
    ar_, ppe_, ap_, acc_, tax_, debt_, eq_ = ar0, ppe0, ap0, acc0, 0.0, debt0, eq0
    rows: List[Dict[str, Any]] = []
    bad_debt = max(0.0, (a.sales.bad_debt_pct + adj.extra_bad_debt_pct) / 100.0)
    new_sales_uncollectible = 0.0
    for k in range(n):
        c = monthly[k]["categories"]
        p = pnl[k]
        collections = c["ar_collections"] + c["new_sales_collections"]
        ar_ += p["revenue"] - collections
        new_sales_uncollectible += p["revenue"] * bad_debt
        ppe_ += plan_m[k]["additions"] - plan_m[k]["depreciation"]
        ppe_ -= _one_time_investing(a, run, k)
        ap_ += p["cogs"] + c["cogs_vendors"] + c["ap_open_bills"]  # payments are negative
        acc_ += p["payroll"] + c["payroll"]
        tax_ += tax_exp[k] + c["taxes"]
        financed = plan_m[k]["additions"] - plan_m[k]["cash_capex"]
        debt_ += financed + c["debt_service"] + p["interest"]  # debt service is negative
        eq_ += p["pretax_profit"] - tax_exp[k] + c["other_operating"] + c["financing_other"]
        r = row(p["label"], monthly[k]["end_cash"], ar_, ppe_, ap_, acc_, tax_, debt_, eq_)
        r["net_income"] = p["pretax_profit"] - tax_exp[k]
        rows.append(r)

    open_total = sum(p["open_amount"] for p in run.projected_ar)
    expected = sum(p["expected_amount"] for p in run.projected_ar)
    return {
        "opening": opening,
        "months": rows,
        "max_abs_check": max([abs(opening["check"])] + [abs(r["check"]) for r in rows]),
        "memo": {
            "existing_ar_expected_uncollectible": open_total - expected,
            "new_sales_expected_uncollectible": new_sales_uncollectible,
            "ar_ending": rows[-1]["receivables"] if rows else ar0,
        },
        "opening_basis": {"ppe_net": ppe0, "ppe_from": "assumption (Capex plan > Opening net PP&E)"},
    }


def _one_time_investing(a: Any, run: Any, k: int) -> float:
    """Signed one-time investing cash in month k (negative = spend, which raises PP&E)."""
    start, end = run.monthly[k]["start"], run.monthly[k]["end"]
    total = 0.0
    for item in a.one_time:
        if item.category == "investing" and start <= item.date < end:
            total += item.amount
    return total
