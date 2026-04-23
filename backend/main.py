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
        "data_source": os.getenv("DATA_SOURCE_TYPE", "csv")
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
        "top_risk": data.get("top_risky_customers", [])[:3],
        "top_actions": data.get("top_recommended_actions", [])[:3],
        "top_payers": data.get("top_expected_payers_next_30_days", [])[:3],
    }


def compact_history(history: List[Dict[str, Any]], max_items: int = 6) -> str:
    trimmed = history[-max_items:]
    return "\n".join([f"{h.get('role', 'user')}: {h.get('content', '')}" for h in trimmed])


def run_clarification_logic(user_message, history=None, ar_context=None, uploaded_context=None):
    history = history or []

    prompt = f"""
You are NEURAFLOW — a finance AI for credit risk and cash forecasting.

Use the data to:
- assess risk
- estimate 30-day cash
- recommend actions

History:
{compact_history(history)}

User:
{user_message}

Data:
{json.dumps(compact_uploaded_context(uploaded_context), indent=2)}

Respond in JSON:
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
            input=prompt
        )

        try:
            return json.loads(response.output_text)
        except Exception:
            return {
                "error": "Model output parsing failed",
                "raw": response.output_text
            }

    except Exception as e:
        print("🔥 OPENAI ERROR:", str(e))
        return {
            "error": f"OpenAI request failed: {str(e)}"
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

    except Exception as e:
        print("🔥 /chat ERROR:", str(e))
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
                    "source_type": os.getenv("DATA_SOURCE_TYPE", "csv")
                }
            else:
                uploaded_context = {
                    "summary": data_source.get_customer_summaries(),
                    "source_type": os.getenv("DATA_SOURCE_TYPE", "csv")
                }

        result = run_clarification_logic(
            message,
            parsed_history,
            ar_context,
            uploaded_context
        )

        return {
            **result,
            "uploaded_context": uploaded_context
        }

    except Exception as e:
        print("🔥 /chat-upload ERROR:", str(e))
        return {"error": str(e)}