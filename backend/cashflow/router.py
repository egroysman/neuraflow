"""HTTP endpoints for the cash flow model, mounted under /cashflow."""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response
from pydantic import BaseModel, Field

from . import ap, ar, assistant, credit, engine, export, gl, macro, trends
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


_VALIDATION_CACHE: dict = {}
SAMPLE_CAVEAT = (
    "This runs on the bundled sample invoices (25 customers, 755 invoices). They contain two clearly different kinds of payer, "
    "so they show that the method works, not how it performs on real businesses. A pilot on real customer data is the real test."
)


def _validation(invoices, horizon_days: int, late_days: int) -> dict:
    """Back-test results, cached because the invoices only change when the data does."""
    key = (horizon_days, late_days, len(invoices), round(sum(i.amount for i in invoices), 2),
           max((i.payment_date for i in invoices if i.payment_date), default=None))
    if key not in _VALIDATION_CACHE:
        if len(_VALIDATION_CACHE) > 20:
            _VALIDATION_CACHE.clear()
        _VALIDATION_CACHE[key] = credit.backtest(invoices, horizon_days=horizon_days, late_days=late_days)
    result = _VALIDATION_CACHE[key]
    return result | {"caveat": SAMPLE_CAVEAT}


@router.get("/credit")
def get_credit(as_of: dt.date | None = None):
    """Payment-behavior score for each customer, using only what was known on the date."""
    invoices = ar.parse_invoices(ar.load_invoice_rows())
    when = as_of or ar.snapshot_date(invoices)
    scores = credit.score_customers(invoices, when)
    return clean({"as_of": when, "customers": scores, "summary": credit.portfolio_summary(scores)})


@router.get("/credit/validation")
def get_credit_validation(horizon_days: int = Query(90, ge=30, le=180), late_days: int = Query(10, ge=0, le=60)):
    """Back-test: replay the score at past dates and compare it with what customers did next."""
    result = _validation(ar.parse_invoices(ar.load_invoice_rows()), horizon_days, late_days)
    return clean({k: v for k, v in result.items() if k != "records"})


@router.get("/credit/validation/export")
def export_credit_validation(horizon_days: int = Query(90, ge=30, le=180), late_days: int = Query(10, ge=0, le=60)):
    """Every scored invoice behind the back-test, as CSV, so the numbers can be audited."""
    result = _validation(ar.parse_invoices(ar.load_invoice_rows()), horizon_days, late_days)
    return Response(
        content=credit.records_csv(result),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="neuraflow_credit_backtest.csv"'},
    )


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
    customer_id: str | None = Field(default=None, max_length=40)  # legacy name for focus
    focus: str | None = Field(default=None, max_length=60)  # customer, vendor, ...
    tab: Literal["forecast", "receivables", "credit", "payroll", "payables", "capex", "balance", "gl", "trends"] = "receivables"
    forecast: ForecastRequest


@router.post("/assistant")
def tab_assistant(req: AssistantRequest):
    """Answer a question about one tab from the same forecast and loaded data the user is looking at."""
    rows = ar.load_invoice_rows()
    bill_rows = ap.load_bill_rows()
    ledger = gl.load_gl()
    result = engine.forecast(rows, req.forecast, bill_rows, ledger)
    invoices = ar.parse_invoices(rows)
    bills = ap.parse_bills(bill_rows)
    as_of = result["as_of"]
    data: dict[str, Any] = {"invoices": invoices, "bills": bills, "focus": req.focus or req.customer_id}
    if req.tab == "gl":
        data["gl"] = gl.overview(as_of, invoices, bills)
    if req.tab == "credit":
        scores = credit.score_customers(invoices, as_of)
        data["credit"] = scores
        data["credit_summary"] = credit.portfolio_summary(scores)
        data["validation"] = _validation(invoices, 90, 10)
    if req.tab == "trends":
        data["trends"] = trends.build_trends(invoices, bills, ar.snapshot_date(invoices) or as_of)
    context = assistant.build_tab_context(req.tab, result, data)
    try:
        answer = assistant.ask(context, req.message, req.history, req.tab)
    except assistant.AssistantUnavailable as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:  # the model call failed: report it without a stack trace
        raise HTTPException(status_code=502, detail=f"The assistant couldn't answer: {e}")
    return clean(answer)


@router.post("/ar-assistant")
def ar_assistant(req: AssistantRequest):
    """Kept for older clients: the receivables assistant."""
    return tab_assistant(req.model_copy(update={"tab": "receivables"}))

