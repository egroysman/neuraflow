"""Per-tab assistants: answer questions from the numbers on each cash flow tab.

Each tab has its own assistant. It is given a compact snapshot of the current
forecast plus the loaded data that tab is built on (invoices, vendor bills,
payroll roster, general ledger, trend history) and nothing else, so its answers
match what the user sees. It may also suggest settings for that tab's what-if
sliders; those are validated and clamped here before they reach the browser.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

from pydantic import ValidationError

from .models import Adjustments

# Which what-if group each tab owns (a tab's assistant may only suggest its own levers).
TAB_GROUPS = {
    "forecast": "operations",
    "receivables": "ar",
    "payroll": "payroll",
    "payables": "payables",
    "capex": "capex",
    "balance": "financing",
    "gl": "ledger",
    "trends": "trends",
}
TAB_ROLES = {
    "forecast": "the overall cash flow forecast (cash balance, P&L, scenarios, alerts)",
    "receivables": "receivables (customers, invoice aging and collections)",
    "payroll": "payroll (the employee roster, pay runs, headcount, bonuses and benefits)",
    "payables": "payables (vendor bills, aging and payment timing)",
    "capex": "capital purchases (planned items, financing, interest and depreciation)",
    "balance": "the balance sheet (cash, receivables, payables, debt and equity)",
    "gl": "the general ledger (trial balance, actuals versus forecast, and how the ledger ties to invoices and bills)",
    "trends": "trends in the business history (revenue, collections, seasonality and customer concentration)",
}
# Sliders the assistant may suggest on the receivables tab (kept for compatibility).
SUGGESTIBLE = list(Adjustments.GROUPS["ar"])


def suggestible(tab: str) -> List[str]:
    return list(Adjustments.GROUPS[TAB_GROUPS[tab]])
MODEL = os.getenv("AR_ASSISTANT_MODEL", "gpt-4.1-mini")
MAX_HISTORY = 8


class AssistantUnavailable(RuntimeError):
    pass


def build_context(result: Dict[str, Any], invoices: List[Any], customer_id: Optional[str] = None) -> Dict[str, Any]:
    """Receivables context (the original assistant)."""
    ar = result["ar"]
    months = result["monthly"]
    k = result["kpis"]["monthly"]
    adj = {name: value for name, value in result["effective_adjustments"].items() if value}
    ctx: Dict[str, Any] = {
        "as_of": str(result["as_of"]),
        "scenario": result["scenario_label"],
        "active_what_ifs": adj,
        "cash": {
            "starting": k["starting_cash"],
            "ending": k["ending_cash"],
            "lowest_balance": k["lowest_balance"],
            "lowest_balance_date": str(k["lowest_balance_date"]),
            "first_negative_date": str(k["first_negative_date"]) if k["first_negative_date"] else None,
        },
        "receivables": {
            "open_total": ar["open_total"],
            "expected_to_collect_total": ar["expected_total"],
            "expected_in_plan_window": ar["expected_in_horizon"],
            "not_expected_to_be_collected": ar["expected_haircut"],
            "aging": [{"bucket": a["label"], "open": a["open_amount"], "invoices": a["invoices"]} for a in ar["aging"]],
        },
        "top_customers": [
            {
                "customer": c["customer_id"],
                "open": c["open_amount"],
                "open_invoices": c["open_invoices"],
                "expected_in_plan_window": c["expected_in_horizon"],
                "avg_days_to_pay": c["avg_days_to_pay"],
                "oldest_days_past_due": c["oldest_days_past_due"],
                "risk": c["risk"],
            }
            for c in ar["customers"][:10]
        ],
        "customer_cash_by_month": [
            {
                "month": p["label"],
                "from_invoices_open_today": round(p["categories"].get("ar_collections", 0.0)),
                "from_new_sales": round(p["categories"].get("new_sales_collections", 0.0)),
            }
            for p in months
        ],
        "impact_of_receivables_what_ifs": result["whatif_impact"]["ar"],
    }
    if customer_id:
        mine = [i for i in invoices if i.customer_id == str(customer_id) and i.open_amount > 0]
        mine.sort(key=lambda i: -i.open_amount)
        ctx["selected_customer"] = {
            "customer": str(customer_id),
            "open_invoices": [
                {"invoice": i.invoice_id, "due": str(i.due_date), "open": i.open_amount, "days_past_due": (result["as_of"] - i.due_date).days}
                for i in mine[:12]
            ],
        }
    return ctx


# ---------------------------------------------------------------------------
# Context for the other tabs
# ---------------------------------------------------------------------------

def _r(x: Any, n: int = 0) -> Any:
    return round(x, n) if isinstance(x, (int, float)) and not isinstance(x, bool) else x


def _base(result: Dict[str, Any], tab: str) -> Dict[str, Any]:
    k = result["kpis"]["monthly"]
    return {
        "as_of": str(result["as_of"]),
        "scenario": result["scenario_label"],
        "active_what_ifs": {n: v for n, v in result["effective_adjustments"].items() if v},
        "cash": {
            "starting": _r(k["starting_cash"]),
            "ending": _r(k["ending_cash"]),
            "lowest_balance": _r(k["lowest_balance"]),
            "lowest_balance_date": str(k["lowest_balance_date"]),
            "first_below_minimum_date": str(k["first_below_min_date"]) if k.get("first_below_min_date") else None,
            "first_negative_date": str(k["first_negative_date"]) if k["first_negative_date"] else None,
        },
        f"impact_of_{TAB_GROUPS[tab]}_what_ifs": result["whatif_impact"][TAB_GROUPS[tab]],
    }


def _ctx_forecast(result, data):
    ctx = _base(result, "forecast")
    ctx["alerts"] = [a["message"] for a in result["alerts"]]
    ctx["months"] = [
        {
            "month": p["label"],
            "net_cash": _r(p["net"]),
            "ending_cash": _r(p["end_cash"]),
            "below_minimum": p["below_min"],
            "cash_in_by_source": {k: _r(v) for k, v in p["categories"].items() if v > 0},
            "cash_out_by_use": {k: _r(v) for k, v in p["categories"].items() if v < 0},
        }
        for p in result["monthly"]
    ]
    ctx["profit_and_loss"] = [
        {k: _r(v) if k != "label" else v for k, v in row.items() if k in ("label", "revenue", "cogs", "payroll", "opex", "depreciation", "interest", "pretax_profit")}
        for row in result["pnl"]
    ]
    ctx["scenarios"] = {
        name: {"ending_cash": _r(c["ending_cash"]), "lowest_balance": _r(c["lowest_balance"]), "goes_negative": bool(c["first_negative_date"])}
        for name, c in result["comparison"].items()
    }
    ctx["macro_overlay"] = result["macro"] if result["macro"].get("applied") else None
    return ctx


def _ctx_payroll(result, data):
    p = result["payroll"]
    ctx = _base(result, "payroll")
    ctx["summary"] = {
        "active_headcount": p["active_headcount"],
        "annual_base_active": _r(p["annual_base_active"]),
        "pay_frequency": p["pay_frequency"],
        "total_cost_in_plan": _r(p["total_cost"]),
        "total_cash_in_plan": _r(p["total_cash"]),
        "opening_accrued_payroll": _r(p["opening_accrued"]),
    }
    ctx["monthly_cost"] = [{"month": m["label"], "cost": _r(c), "headcount": h} for m, c, h in zip(result["monthly"], p["monthly"], p["headcount"])]
    ctx["by_department_monthly_cost"] = {d: [_r(v) for v in vals] for d, vals in p["by_department"].items()}
    ctx["employees"] = [
        {k: e.get(k) for k in ("id", "department", "title", "pay_type", "annual_base", "hire_date", "term_date", "bonus_pct", "benefits_monthly", "status")}
        for e in p["employees"]
    ]
    ctx["next_pay_runs"] = [{k: _r(r.get(k)) if k != "date" else str(r.get(k)) for k in r if k in ("date", "gross", "cash", "net")} for r in p["runs"][:6]]
    return ctx


def _ctx_payables(result, data):
    ap = result["ap"]
    ctx = _base(result, "payables")
    ctx["payables"] = {
        "open_total": _r(ap["open_total"]),
        "open_bills": ap["open_bills"],
        "overdue_total": _r(ap["overdue_total"]),
        "overdue_pct": ap["overdue_pct"],
        "actual_days_to_pay": ap["actual_dpo_days"],
        "top3_vendor_share_pct": ap["top3_share_pct"],
        "aging": [{"bucket": a["label"], "open": _r(a["open_amount"]), "bills": a["bills"]} for a in ap["aging"]],
        "by_category": ap["by_category"],
        "due_by_month": ap["due_by_month"],
    }
    ctx["vendors"] = [{k: v for k, v in x.items() if k != "vendor_id" or True} for x in ap["vendors"]]
    ctx["upcoming_bills"] = ap["upcoming"]
    ctx["monthly_vendor_spend"] = ap["monthly_spend"]
    focus = data.get("focus")
    if focus:
        mine = [b for b in data.get("bills", []) if focus in (b.vendor_id, b.vendor_name) and b.open_amount > 0]
        mine.sort(key=lambda b: -b.open_amount)
        ctx["selected_vendor"] = {
            "vendor": focus,
            "open_bills": [{"bill": b.bill_id, "due": str(b.due_date), "open": b.open_amount} for b in mine[:12]],
        }
    return ctx


def _ctx_capex(result, data):
    cx = result["capex"]
    ctx = _base(result, "capex")
    ctx["totals"] = {k: _r(v) for k, v in cx["totals"].items()}
    ctx["items"] = cx["items"]
    ctx["monthly"] = [{"month": m["label"], **{k: _r(v) for k, v in c.items() if k != "label"}} for m, c in zip(result["monthly"], cx["monthly"])] if cx["monthly"] and isinstance(cx["monthly"][0], dict) else [_r(v) for v in cx["monthly"]]
    ctx["interest_by_month"] = [_r(v) for v in cx["interest"]]
    ctx["depreciation_by_month"] = [_r(v) for v in cx["depreciation"]]
    return ctx


def _ctx_balance(result, data):
    bs = result["balance_sheet"]
    keep = ("label", "cash", "receivables", "ppe_net", "payables", "accrued_payroll", "taxes_payable", "debt", "equity", "working_capital", "net_debt", "check")
    ctx = _base(result, "balance")
    ctx["opening"] = {k: _r(bs["opening"].get(k), 2 if k == "check" else 0) for k in keep}
    ctx["months"] = [{k: _r(m.get(k), 2 if k == "check" else 0) for k in keep} for m in bs["months"]]
    ctx["memo"] = {k: _r(v) for k, v in bs["memo"].items()}
    ctx["balances_every_month"] = bs["max_abs_check"] < 0.5
    return ctx


def _ctx_gl(result, data):
    g = result["gl"]
    ctx = _base(result, "gl")
    ctx["actual_vs_forecast_by_month"] = [{k: _r(v) if k != "label" else v for k, v in row.items()} for row in g["timeline"]]
    ctx["baselines_vs_forecast"] = [{k: _r(v, 1) if k != "label" else v for k, v in row.items()} for row in g["baseline_check"]]
    ctx["baseline_months"] = g["baseline_window"]
    ctx["variance"] = g["variance"]
    ov = data.get("gl") or {}
    if ov:
        ctx["ledger"] = {
            "first_date": str(ov.get("first_date")),
            "last_date": str(ov.get("last_date")),
            "entries": ov.get("entry_count"),
            "tie_outs": [{"check": t["label"], "ledger": _r(t["ledger"]), "source": _r(t["source"]), "ok": t["ok"]} for t in ov.get("tie_out", [])],
            "trial_balance": ov.get("trial_balance"),
        }
    return ctx


def _ctx_trends(result, data):
    t = data.get("trends") or {}
    ctx = _base(result, "trends")
    ctx["signals"] = [
        {k: s.get(k) for k in ("label", "current", "previous", "change", "change_unit", "tone", "note")} for s in t.get("signals", [])
    ]
    ctx["monthly_history"] = [{k: _r(v) if isinstance(v, float) else v for k, v in m.items()} for m in t.get("months", [])]
    ctx["implied_growth"] = t.get("implied")
    ctx["customer_concentration"] = t.get("concentration")
    ctx["seasonality"] = t.get("seasonality")
    ctx["caveats"] = t.get("caveats")
    return ctx


CONTEXTS = {
    "forecast": _ctx_forecast,
    "payroll": _ctx_payroll,
    "payables": _ctx_payables,
    "capex": _ctx_capex,
    "balance": _ctx_balance,
    "gl": _ctx_gl,
    "trends": _ctx_trends,
}


def build_tab_context(tab: str, result: Dict[str, Any], data: Dict[str, Any]) -> Dict[str, Any]:
    """Snapshot for one tab. ``data`` carries the loaded datasets and an optional ``focus``."""
    if tab not in TAB_GROUPS:
        raise ValueError(f"Unknown tab: {tab}")
    if tab == "receivables":
        return build_context(result, data.get("invoices", []), data.get("focus"))
    return CONTEXTS[tab](result, data)


def build_prompt(context: Dict[str, Any], message: str, history: List[Dict[str, Any]], tab: str = "receivables") -> str:
    convo = "\n".join(f"{h.get('role', 'user')}: {str(h.get('content', ''))[:600]}" for h in history[-MAX_HISTORY:])
    bounds = {}
    for name in suggestible(tab):
        field = Adjustments.model_fields[name]
        lo = next((m.ge for m in field.metadata if hasattr(m, "ge")), None)
        hi = next((m.le for m in field.metadata if hasattr(m, "le")), None)
        bounds[name] = {"min": lo, "max": hi, "meaning": field.description}
    return f"""You are the assistant for the {tab} tab of a cash flow model; this tab covers {TAB_ROLES[tab]}. Answer using ONLY the data below, which is exactly what the user sees on screen and in the loaded data behind it.
Be concrete: name customers, vendors, employees, accounts, dollar amounts and dates from the data. If the data cannot answer, say what is missing. Do not invent names, numbers or contact details. If the question belongs on another tab, say which tab.
Write 1 to 3 short plain paragraphs. No markdown tables and no JSON inside the answer.

If a what-if would help the user see the effect of something, you may suggest slider settings, using ONLY these fields and ranges:
{json.dumps(bounds)}
Never suggest more than three settings. Omit "suggested_whatifs" when none would help.

Data:
{json.dumps(context, default=str)}

Conversation so far:
{convo}

User question:
{message}

Return ONLY valid JSON of this shape:
{{"answer": "", "suggested_whatifs": {{}}, "follow_ups": ["", ""]}}"""


def _default_complete(prompt: str) -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        raise AssistantUnavailable("The assistant needs an OpenAI API key on the backend (OPENAI_API_KEY).")
    from openai import OpenAI  # imported lazily so the model works without the package at import time

    response = OpenAI(api_key=key).responses.create(model=MODEL, input=prompt)
    return response.output_text


# Replaceable in tests.
complete: Callable[[str], str] = _default_complete


def validate_suggestions(raw: Any, tab: str = "receivables") -> Dict[str, float]:
    """Keep only this tab's levers with in-range values."""
    allowed = suggestible(tab)
    out: Dict[str, float] = {}
    if not isinstance(raw, dict):
        return out
    for name, value in raw.items():
        if name not in allowed or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        try:
            Adjustments(**{name: value})
        except ValidationError:
            continue
        out[name] = value
        if len(out) == 3:
            break
    return out


def ask(context: Dict[str, Any], message: str, history: List[Dict[str, Any]], tab: str = "receivables") -> Dict[str, Any]:
    text = complete(build_prompt(context, message, history, tab))
    try:
        start, end = text.index("{"), text.rindex("}") + 1
        parsed = json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        return {"answer": text.strip(), "suggested_whatifs": {}, "follow_ups": []}
    answer = parsed.get("answer", "")
    if not isinstance(answer, str):
        answer = json.dumps(answer)
    follow = parsed.get("follow_ups") or []
    return {
        "answer": answer.strip(),
        "suggested_whatifs": validate_suggestions(parsed.get("suggested_whatifs"), tab),
        "follow_ups": [str(f) for f in follow if isinstance(f, str) and f.strip()][:3],
    }
