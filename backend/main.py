import os
import json
from typing import List, Dict, Any, Optional
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from openai import OpenAI
from dotenv import load_dotenv
from ar_context import get_ar_context
from data_sources import get_data_source

load_dotenv(dotenv_path=".env")

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
data_source = get_data_source()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",
        "https://neuraflow-qe7yhdptc-egroysmans-projects.vercel.app",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str
    history: List[Dict[str, Any]] = []
    customer_id: Optional[str] = None


@app.get("/")
def read_root():
    return {
        "message": "Clarifying AI is running",
        "data_source": os.getenv("DATA_SOURCE_TYPE", "csv")
    }


def compact_uploaded_context(uploaded_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not uploaded_context:
        return {"note": "No uploaded or direct data context provided."}

    data = uploaded_context.get("summary", uploaded_context)

    compact = {
        "source_type": uploaded_context.get("source_type", data.get("source_type", "csv")),
        "row_count": data.get("row_count", 0),
        "customer_count": data.get("customer_count", 0),
        "total_invoice_amount": data.get("total_invoice_amount", 0),
        "portfolio_expected_cash_next_30_days": data.get("portfolio_expected_cash_next_30_days", 0),
        "aging_buckets": data.get("aging_buckets", {}),
        "top_risky_customers": [],
        "top_recommended_actions": [],
        "top_customers_by_exposure": [],
        "top_customers_by_overdue": [],
        "top_expected_payers_next_30_days": [],
    }

    for customer in (data.get("top_risky_customers", []) or [])[:5]:
        compact["top_risky_customers"].append({
            "customer_id": customer.get("customer_id"),
            "total_amount": customer.get("total_amount"),
            "overdue_amount": customer.get("overdue_amount"),
            "ml_risk_prediction": customer.get("ml_risk_prediction"),
            "ml_risk_probability": customer.get("ml_risk_probability"),
            "predicted_days_to_pay": customer.get("predicted_days_to_pay"),
            "predicted_payment_date": customer.get("predicted_payment_date"),
            "recommended_action": customer.get("recommended_action"),
            "action_priority": customer.get("action_priority"),
            "predicted_amount_paid_next_30_days": customer.get("predicted_amount_paid_next_30_days"),
            "predicted_collection_rate_next_30_days": customer.get("predicted_collection_rate_next_30_days"),
        })

    for customer in (data.get("top_recommended_actions", []) or [])[:5]:
        compact["top_recommended_actions"].append({
            "customer_id": customer.get("customer_id"),
            "overdue_amount": customer.get("overdue_amount"),
            "ml_risk_prediction": customer.get("ml_risk_prediction"),
            "ml_risk_probability": customer.get("ml_risk_probability"),
            "predicted_payment_date": customer.get("predicted_payment_date"),
            "recommended_action": customer.get("recommended_action"),
            "action_priority": customer.get("action_priority"),
            "action_reason": customer.get("action_reason"),
            "predicted_amount_paid_next_30_days": customer.get("predicted_amount_paid_next_30_days"),
            "predicted_collection_rate_next_30_days": customer.get("predicted_collection_rate_next_30_days"),
        })

    for customer in (data.get("top_customers_by_exposure", []) or [])[:5]:
        compact["top_customers_by_exposure"].append({
            "customer_id": customer.get("customer_id"),
            "total_amount": customer.get("total_amount"),
            "overdue_amount": customer.get("overdue_amount"),
            "ml_risk_probability": customer.get("ml_risk_probability"),
        })

    for customer in (data.get("top_customers_by_overdue", []) or [])[:5]:
        compact["top_customers_by_overdue"].append({
            "customer_id": customer.get("customer_id"),
            "overdue_amount": customer.get("overdue_amount"),
            "ml_risk_probability": customer.get("ml_risk_probability"),
            "recommended_action": customer.get("recommended_action"),
        })

    for customer in (data.get("top_expected_payers_next_30_days", []) or [])[:5]:
        compact["top_expected_payers_next_30_days"].append({
            "customer_id": customer.get("customer_id"),
            "predicted_amount_paid_next_30_days": customer.get("predicted_amount_paid_next_30_days"),
            "predicted_collection_rate_next_30_days": customer.get("predicted_collection_rate_next_30_days"),
            "predicted_payment_date": customer.get("predicted_payment_date"),
            "ml_risk_prediction": customer.get("ml_risk_prediction"),
            "ml_risk_probability": customer.get("ml_risk_probability"),
        })

    if uploaded_context.get("customer_detail"):
        customer = uploaded_context["customer_detail"]
        compact["customer_detail"] = {
            "customer_id": customer.get("customer_id"),
            "invoice_count": customer.get("invoice_count"),
            "total_amount": customer.get("total_amount"),
            "overdue_amount": customer.get("overdue_amount"),
            "ml_risk_prediction": customer.get("ml_risk_prediction"),
            "ml_risk_probability": customer.get("ml_risk_probability"),
            "predicted_days_to_pay": customer.get("predicted_days_to_pay"),
            "predicted_payment_date": customer.get("predicted_payment_date"),
            "recommended_action": customer.get("recommended_action"),
            "action_priority": customer.get("action_priority"),
            "action_reason": customer.get("action_reason"),
            "latest_due_date": customer.get("latest_due_date"),
            "oldest_invoice_date": customer.get("oldest_invoice_date"),
            "behavior_summary": customer.get("behavior_summary"),
            "predicted_amount_paid_next_30_days": customer.get("predicted_amount_paid_next_30_days"),
            "predicted_collection_rate_next_30_days": customer.get("predicted_collection_rate_next_30_days"),
        }

    return compact


def compact_history(history: List[Dict[str, Any]], max_items: int = 8) -> str:
    trimmed = history[-max_items:]
    history_text = ""
    for item in trimmed:
        role = item.get("role", "user")
        content = item.get("content", "")
        if len(content) > 500:
            content = content[:500] + "..."
        history_text += f"{role}: {content}\n"
    return history_text


def run_clarification_logic(user_message, history=None, ar_context=None, uploaded_context=None):
    if history is None:
        history = []

    history_text = compact_history(history)
    ar_context_text = json.dumps(ar_context, indent=2) if ar_context else "No AR context provided."
    ai_context = compact_uploaded_context(uploaded_context)
    uploaded_context_text = json.dumps(ai_context, indent=2)

    prompt = f"""
You are NEURAFLOW, a finance AI designed to help professionals make judgment calls around credit risk and cash prediction.

Your job:
1. Use the conversation history
2. Use the AR context if provided
3. Use uploaded finance summary, ML predictions, and recommended actions if provided
4. Determine if enough information exists to make a decision
5. If yes, give a clear recommendation
6. If not, ask one precise clarifying question

You think like:
- a finance manager
- a controller
- a credit manager
- a collections leader

Focus on:
- receivables exposure
- invoice concentration
- overdue balances
- aging profile
- customer-level ML risk signals
- predicted timing of payment
- expected cash in the next 30 days
- recommended collection actions
- practical next actions

Behavior rules:
- Do not ask the same question twice
- If the user already answered the key issue, move to a recommendation
- Ask only one question when a critical decision factor is missing
- Prefer a practical recommendation with assumptions over endless clarification
- Keep questions short and direct
- Keep answers practical and business-oriented
- Treat uploaded analytics as factual source data
- When action recommendations exist, use them directly
- Be decisive when the data supports a clear action
- Do not ask to inspect raw rows if summary data already exists

Conversation history:
{history_text}

AR context:
{ar_context_text}

Compact portfolio context:
{uploaded_context_text}

Latest user message:
{user_message}

Return only valid JSON in this exact format:

{{
  "confidence": 0.0,
  "is_ambiguous": true,
  "interpretations": ["", ""],
  "restate": "",
  "clarifying_question": "",
  "answer": "",
  "assumptions": ""
}}

Rules:
- If enough information exists, confidence should usually be 0.7 or higher and provide an answer
- If key information is missing, confidence should be below 0.6 and ask one clarifying question
- If answering, leave clarifying_question as an empty string
- If asking a clarifying question, leave answer as an empty string
- Restate should reflect updated understanding after using history and data context
"""

    response = client.responses.create(
        model="gpt-5.4",
        input=prompt
    )

    try:
        return json.loads(response.output_text)
    except Exception:
        return {
            "error": "Failed to parse response",
            "raw": response.output_text
        }


@app.post("/chat")
def chat(req: ChatRequest):
    ar_context = get_ar_context(req.customer_id) if req.customer_id else None

    if req.customer_id:
        customer_detail = data_source.get_customer_detail(req.customer_id)
        all_data = data_source.get_customer_summaries()
        direct_context = {
            "customer_detail": customer_detail,
            "summary": all_data,
            "source_type": os.getenv("DATA_SOURCE_TYPE", "csv")
        }
    else:
        direct_context = {
            "summary": data_source.get_customer_summaries(),
            "source_type": os.getenv("DATA_SOURCE_TYPE", "csv")
        }

    result = run_clarification_logic(req.message, req.history, ar_context, direct_context)

    return {
        **result,
        "uploaded_context": direct_context
    }


@app.post("/chat-upload")
async def chat_upload(
    message: str = Form(...),
    history: str = Form("[]"),
    customer_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    parsed_history = json.loads(history) if history else []
    ar_context = get_ar_context(customer_id) if customer_id else None

    uploaded_context = None

    if file:
        file_bytes = await file.read()
        uploaded_context = data_source.get_customer_summaries(file_bytes)
    else:
        if customer_id:
            customer_detail = data_source.get_customer_detail(customer_id)
            all_data = data_source.get_customer_summaries()
            uploaded_context = {
                "customer_detail": customer_detail,
                "summary": all_data,
                "source_type": os.getenv("DATA_SOURCE_TYPE", "csv")
            }
        else:
            uploaded_context = {
                "summary": data_source.get_customer_summaries(),
                "source_type": os.getenv("DATA_SOURCE_TYPE", "csv")
            }

    result = run_clarification_logic(message, parsed_history, ar_context, uploaded_context)

    return {
        **result,
        "uploaded_context": uploaded_context
    }