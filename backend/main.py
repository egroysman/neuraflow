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

load_dotenv()

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
data_source = get_data_source()

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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
        "message": "NEURAFLOW backend is running",
        "data_source": os.getenv("DATA_SOURCE_TYPE", "csv"),
    }


def compact_uploaded_context(uploaded_context: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not uploaded_context:
        return {"note": "No uploaded context"}

    data = uploaded_context.get("summary", uploaded_context)

    return {
        "customer_count": data.get("customer_count", 0),
        "total_invoice_amount": data.get("total_invoice_amount", 0),
        "expected_cash_30d": data.get("portfolio_expected_cash_next_30_days", 0),
        "aging": data.get("aging_buckets", {}),
        "top_risk": data.get("top_risky_customers", [])[:5],
        "top_actions": data.get("top_recommended_actions", [])[:5],
        "top_payers": data.get("top_expected_payers_next_30_days", [])[:5],
    }


def compact_history(history: List[Dict[str, Any]], max_items: int = 6) -> str:
    trimmed = history[-max_items:]
    return "\n".join(
        [f"{h.get('role', 'user')}: {h.get('content', '')}" for h in trimmed]
    )


def clean_answer_text(answer: Any) -> str:
    if answer is None:
        return ""

    if isinstance(answer, str):
        return answer

    if isinstance(answer, list):
        return " ".join([str(item) for item in answer])

    if isinstance(answer, dict):
        parts = []

        expected_cash = (
            answer.get("expected_cash_30_days")
            or answer.get("expected_cash_30d")
            or answer.get("expected_cash")
            or answer.get("cash_forecast")
        )

        risk_customers = (
            answer.get("highest_risk_customers")
            or answer.get("top_risk_customers")
            or answer.get("risky_customers")
        )

        actions = (
            answer.get("recommended_finance_actions")
            or answer.get("recommended_actions")
            or answer.get("actions")
        )

        if expected_cash:
            parts.append(
                f"Expected cash over the next 30 days is approximately {expected_cash}."
            )

        if risk_customers:
            parts.append(
                f"The highest-risk customers are {risk_customers}. These accounts should be reviewed first because they show elevated risk based on overdue exposure, payment behavior, and credit indicators."
            )

        if actions:
            parts.append(
                f"Finance should focus on the following actions: {actions}."
            )

        if parts:
            return " ".join(parts)

        return " ".join([f"{key}: {value}." for key, value in answer.items()])

    return str(answer)


def normalize_model_response(parsed: Dict[str, Any]) -> Dict[str, Any]:
    parsed["answer"] = clean_answer_text(parsed.get("answer", ""))

    if parsed.get("assumptions") is not None:
        parsed["assumptions"] = clean_answer_text(parsed.get("assumptions", ""))

    if parsed.get("clarifying_question") is not None:
        parsed["clarifying_question"] = clean_answer_text(
            parsed.get("clarifying_question", "")
        )

    if parsed.get("restate") is not None:
        parsed["restate"] = clean_answer_text(parsed.get("restate", ""))

    return parsed


def run_clarification_logic(user_message, history=None, ar_context=None, uploaded_context=None):
    history = history or []

    prompt = f"""
You are NEURAFLOW, a finance AI for credit risk and cash forecasting.

Use the available data to:
- assess credit risk
- estimate expected cash over the next 30 days
- identify risky customers
- recommend practical finance or collections actions

Conversation history:
{compact_history(history)}

User question:
{user_message}

Data summary:
{json.dumps(compact_uploaded_context(uploaded_context), indent=2)}

Return ONLY valid JSON.

The "answer" field must be written as a polished human finance summary.

Do NOT put JSON, dictionaries, object keys, markdown tables, or code-like formatting inside the "answer" field.

Write the answer like a person. Use 1 to 3 short paragraphs.

Example answer style:
"Based on the portfolio, expected cash over the next 30 days is approximately $X. The highest-risk customers appear to be Customer A, Customer B, and Customer C because they combine overdue exposure with weaker payment behavior. Finance should prioritize outreach to those accounts first, while separately monitoring customers expected to pay within the forecast window."

Use this exact JSON shape:
{{
  "confidence": 0.0,
  "is_ambiguous": false,
  "interpretations": [],
  "restate": "",
  "clarifying_question": "",
  "answer": "",
  "assumptions": ""
}}
"""

    try:
        response = client.responses.create(
            model="gpt-4.1-mini",
            input=prompt,
        )

        try:
            parsed = json.loads(response.output_text)
            return normalize_model_response(parsed)

        except Exception:
            return {
                "confidence": 0.6,
                "is_ambiguous": False,
                "interpretations": [],
                "restate": "",
                "clarifying_question": "",
                "answer": clean_answer_text(response.output_text),
                "assumptions": "Model returned non-JSON text, so the response was cleaned and displayed.",
            }

    except Exception as e:
        print("OPENAI ERROR:", str(e))
        return {
            "confidence": 0.0,
            "is_ambiguous": True,
            "interpretations": [],
            "restate": "",
            "clarifying_question": "",
            "answer": "",
            "assumptions": "",
            "error": f"OpenAI request failed: {str(e)}",
        }


@app.post("/chat")
def chat(req: ChatRequest):
    try:
        ar_context = get_ar_context(req.customer_id) if req.customer_id else None

        if req.customer_id:
            customer_detail = data_source.get_customer_detail(req.customer_id)
            all_data = data_source.get_customer_summaries()
            direct_context = {
                "customer_detail": customer_detail,
                "summary": all_data,
                "source_type": os.getenv("DATA_SOURCE_TYPE", "csv"),
            }
        else:
            direct_context = {
                "summary": data_source.get_customer_summaries(),
                "source_type": os.getenv("DATA_SOURCE_TYPE", "csv"),
            }

        result = run_clarification_logic(
            req.message,
            req.history,
            ar_context,
            direct_context,
        )

        return {**result, "uploaded_context": direct_context}

    except Exception as e:
        print("/chat ERROR:", str(e))
        return {"error": str(e)}


@app.post("/chat-upload")
async def chat_upload(
    message: str = Form(...),
    history: str = Form("[]"),
    customer_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
):
    try:
        parsed_history = json.loads(history) if history else []
        ar_context = get_ar_context(customer_id) if customer_id else None

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
                    "source_type": os.getenv("DATA_SOURCE_TYPE", "csv"),
                }
            else:
                uploaded_context = {
                    "summary": data_source.get_customer_summaries(),
                    "source_type": os.getenv("DATA_SOURCE_TYPE", "csv"),
                }

        result = run_clarification_logic(
            message,
            parsed_history,
            ar_context,
            uploaded_context,
        )

        return {**result, "uploaded_context": uploaded_context}

    except Exception as e:
        print("/chat-upload ERROR:", str(e))
        return {"error": str(e)}