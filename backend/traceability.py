import json
import os
from datetime import datetime
from typing import Any, Dict, List


TRACE_FILE = "traceability_log.jsonl"


def _safe_get_summary(uploaded_context: Dict[str, Any]) -> Dict[str, Any]:
    if not uploaded_context:
        return {}

    if "summary" in uploaded_context:
        return uploaded_context.get("summary") or {}

    return uploaded_context


def create_trace_record(
    user_message: str,
    uploaded_context: Dict[str, Any],
    model_result: Dict[str, Any],
    model_name: str = "gpt-4.1-mini",
) -> Dict[str, Any]:
    data = _safe_get_summary(uploaded_context)

    return {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "model": model_name,
        "user_question": user_message,
        "data_source": uploaded_context.get("source_type", "csv")
        if uploaded_context
        else "unknown",
        "metrics_used": {
            "customer_count": data.get("customer_count"),
            "total_invoice_amount": data.get("total_invoice_amount"),
            "expected_cash_30d": data.get(
                "portfolio_expected_cash_next_30_days"
            ),
            "aging_buckets": data.get("aging_buckets"),
        },
        "evidence_used": {
            "top_risk_customers": data.get("top_risky_customers", [])[:5],
            "top_recommended_actions": data.get("top_recommended_actions", [])[
                :5
            ],
            "top_expected_payers_30d": data.get(
                "top_expected_payers_next_30_days", []
            )[:5],
        },
        "model_output": {
            "confidence": model_result.get("confidence"),
            "answer": model_result.get("answer"),
            "assumptions": model_result.get("assumptions"),
        },
    }


def save_trace(record: Dict[str, Any]) -> None:
    with open(TRACE_FILE, "a", encoding="utf-8") as file:
        file.write(json.dumps(record, default=str) + "\n")


def get_recent_traces(limit: int = 20) -> List[Dict[str, Any]]:
    if not os.path.exists(TRACE_FILE):
        return []

    with open(TRACE_FILE, "r", encoding="utf-8") as file:
        lines = file.readlines()

    return [json.loads(line) for line in lines[-limit:]]