"""HTTP endpoints for the cash flow model, mounted under /cashflow."""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import ap, ar, assistant, engine, export, gl, macro, trends
from .models import SCENARIO_LABELS, SCENARIO_PRESETS, ForecastRequest

router = APIRouter(prefix="/cashflow", tags=["cashflow"])

PLACEHOLDER_NOTE = (
    "Start date, revenue run-rate and days-to-pay come from your invoice data. "
    "Starting cash, payroll, operating expenses, debt and one-time items are "
    "illustrative placeholders scaled to that revenue - replace them with your real numbers. "
    "Vendor bills come from the bundled sample payables dataset."
)


def clean(value: Any) -> Any:
    """Make engine output JSON-safe: dates to ISO strings, floats rounded."""
    if isinstance(value, BaseModel):
        return clean(value.model_dump())
    if isinstance(value, dict):
        return {k: clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    if isinstance(value, float):
        return round(value, 2)
    return value


@router.get("/defaults")
def defaults():
    rows = ar.load_invoice_rows()
    derived = engine.default_assumptions(
        rows, bill_rows=ap.load_bill_rows(), payroll_rows=gl.load_payroll_rows(), gl_data=gl.load_gl()
    )
    return clean(
        {
            "assumptions": derived["assumptions"],
            "data_summary": derived["data_summary"],
            "scenarios": {
                name: {"label": SCENARIO_LABELS[name], "adjustments": preset}
                for name, preset in SCENARIO_PRESETS.items()
            },
            "note": PLACEHOLDER_NOTE,
        }
    )


@router.get("/macro")
def get_macro(refresh: bool = False):
    """Live macro indicators (FRED) plus the overlay values they suggest."""
    return clean(macro.get_macro(force=refresh))


@router.get("/trends")
def get_trends(as_of: dt.date | None = None):
    """Micro trends from the invoice and bill history."""
    invoices = ar.parse_invoices(ar.load_invoice_rows())
    bills = ap.parse_bills(ap.load_bill_rows())
    when = as_of or ar.snapshot_date(invoices)
    return clean(trends.build_trends(invoices, bills, when))


@router.get("/gl")
def get_gl(as_of: dt.date | None = None):
    """Sample general ledger: trial balance, monthly actuals, baselines and tie-outs."""
    invoices = ar.parse_invoices(ar.load_invoice_rows())
    bills = ap.parse_bills(ap.load_bill_rows())
    data = gl.overview(as_of or ar.snapshot_date(invoices), invoices, bills)
    return clean(data) if data else {"available": False}


@router.post("/forecast")
def run_forecast(req: ForecastRequest):
    rows = ar.load_invoice_rows()
    return clean(engine.forecast(rows, req, ap.load_bill_rows(), gl.load_gl()))


@router.post("/export")
def export_forecast(req: ForecastRequest, format: Literal["xlsx", "csv"] = "xlsx"):
    rows = ar.load_invoice_rows()
    result = engine.forecast(rows, req, ap.load_bill_rows(), gl.load_gl())
    stem = f"neuraflow_cashflow_{req.scenario}_{req.assumptions.general.as_of.isoformat()}"
    if format == "csv":
        body = export.build_csv(result).encode("utf-8")
        media = "text/csv"
    else:
        body = export.build_xlsx(result, req.assumptions)
        media = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return Response(
        content=body,
        media_type=media,
        headers={
            "Content-Disposition": f'attachment; filename="{stem}.{format}"',
            # Let a browser on another origin (the Next.js app) read the filename.
            "Access-Control-Expose-Headers": "Content-Disposition",
        },
    )


class AssistantRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1500)
    history: list[dict[str, Any]] = Field(default_factory=list, max_length=40)
    customer_id: str | None = Field(default=None, max_length=40)
    forecast: ForecastRequest


@router.post("/ar-assistant")
def ar_assistant(req: AssistantRequest):
    """Answer a receivables question from the same forecast the user is looking at."""
    rows = ar.load_invoice_rows()
    result = engine.forecast(rows, req.forecast, ap.load_bill_rows(), gl.load_gl())
    context = assistant.build_context(result, ar.parse_invoices(rows), req.customer_id)
    try:
        answer = assistant.ask(context, req.message, req.history)
    except assistant.AssistantUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # the model call failed: report it without a stack trace
        raise HTTPException(status_code=502, detail=f"The assistant couldn't answer: {e}")
    return clean(answer)
