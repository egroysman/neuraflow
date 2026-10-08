"""AR assistant: answers questions from the numbers on the Receivables tab.

The model is given a compact snapshot of the current forecast (receivables, aging,
top customers, customer cash by month, active what-ifs and their cash impact) and
nothing else, so its answers match what the user sees. It may also suggest
settings for the receivables what-if sliders; those are validated and clamped
here before they reach the browser.
"""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List, Optional

from pydantic import ValidationError

from .models import Adjustments

# Sliders the assistant may suggest (receivables levers only).
SUGGESTIBLE = list(Adjustments.GROUPS["ar"])
MODEL = os.getenv("AR_ASSISTANT_MODEL", "gpt-4.1-mini")
MAX_HISTORY = 8


class AssistantUnavailable(RuntimeError):
    pass


def build_context(result: Dict[str, Any], invoices: List[Any], customer_id: Optional[str] = None) -> Dict[str, Any]:
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


def build_prompt(context: Dict[str, Any], message: str, history: List[Dict[str, Any]]) -> str:
    convo = "\n".join(f"{h.get('role', 'user')}: {str(h.get('content', ''))[:600]}" for h in history[-MAX_HISTORY:])
    bounds = {}
    for name in SUGGESTIBLE:
        field = Adjustments.model_fields[name]
        lo = next((m.ge for m in field.metadata if hasattr(m, "ge")), None)
        hi = next((m.le for m in field.metadata if hasattr(m, "le")), None)
        bounds[name] = {"min": lo, "max": hi, "meaning": field.description}
    return f"""You are the receivables assistant inside a cash flow model. Answer using ONLY the data below, which is exactly what the user sees on screen.
Be concrete: name customers, dollar amounts and dates from the data. If the data cannot answer, say what is missing. Do not invent customers, numbers or contact details.
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


def validate_suggestions(raw: Any) -> Dict[str, float]:
    """Keep only known receivables levers with in-range values."""
    out: Dict[str, float] = {}
    if not isinstance(raw, dict):
        return out
    for name, value in raw.items():
        if name not in SUGGESTIBLE or isinstance(value, bool) or not isinstance(value, (int, float)):
            continue
        try:
            Adjustments(**{name: value})
        except ValidationError:
            continue
        out[name] = value
        if len(out) == 3:
            break
    return out


def ask(context: Dict[str, Any], message: str, history: List[Dict[str, Any]]) -> Dict[str, Any]:
    text = complete(build_prompt(context, message, history))
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
        "suggested_whatifs": validate_suggestions(parsed.get("suggested_whatifs")),
        "follow_ups": [str(f) for f in follow if isinstance(f, str) and f.strip()][:3],
    }
