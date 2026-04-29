from fastapi import FastAPI, Form
from fastapi.middleware.cors import CORSMiddleware
import json
import os

from traceability import create_trace_record, save_trace, get_recent_traces


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# -----------------------------
# MOCK ANALYTICS (replace later)
# -----------------------------
def run_clarification_logic(message, history, ar_context, uploaded_context):
    summary = uploaded_context.get("summary", {})

    expected_cash = summary.get("portfolio_expected_cash_next_30_days", 125000)
    risky = summary.get("top_risky_customers", ["C1001", "C1023"])
    actions = summary.get(
        "top_recommended_actions",
        ["Escalate overdue accounts", "Prioritize collections"],
    )

    return {
        "confidence": 1.0,
        "is_ambiguous": False,
        "interpretations": [],
        "restate": message,
        "clarifying_question": "",
        "answer": f"Based on current invoice and payment behavior, expected cash over the next 30 days is approximately ${expected_cash:,.0f}. A small group of customers is driving most of the risk, including {', '.join(risky[:2])}. Recommended actions include focusing collections efforts on these accounts and prioritizing overdue balances.",
        "assumptions": "Based on aggregated invoice and payment behavior patterns.",
        "expected_cash_30_days": expected_cash,
        "highest_risk_customers": risky,
        "recommended_finance_actions": actions,
    }


# -----------------------------
# MAIN ENDPOINT
# -----------------------------
@app.post("/chat-upload")
def chat_upload(
    message: str = Form(...),
    history: str = Form(...),
):
    try:
        parsed_history = json.loads(history)
    except Exception:
        parsed_history = []

    # Simulated uploaded context (replace with real data source)
    uploaded_context = {
        "source_type": "csv",
        "summary": {
            "customer_count": 120,
            "total_invoice_amount": 2500000,
            "portfolio_expected_cash_next_30_days": 185000,
            "top_risky_customers": ["C1045", "C1022", "C1101"],
            "top_recommended_actions": [
                "Escalate high-risk accounts",
                "Tighten payment terms",
            ],
            "top_expected_payers_next_30_days": ["C1000", "C1005"],
        },
    }

    ar_context = {}

    result = run_clarification_logic(
        message,
        parsed_history,
        ar_context,
        uploaded_context,
    )

    # -----------------------------
    # TRACEABILITY LAYER
    # -----------------------------
    trace_record = create_trace_record(
        user_message=message,
        uploaded_context=uploaded_context,
        model_result=result,
    )

    save_trace(trace_record)

    return {
        **result,
        "uploaded_context": uploaded_context,
        "traceability": trace_record,
    }


# -----------------------------
# TRACE VIEW ENDPOINT
# -----------------------------
@app.get("/traceability")
def traceability():
    return {
        "records": get_recent_traces(20)
    }