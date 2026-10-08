"""HTTP endpoints for the cash flow model, mounted under /cashflow."""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from fastapi import APIRouter
from fastapi.responses import Response
from pydantic import BaseModel

from . import ar, engine, export
from .models import SCENARIO_LABELS, SCENARIO_PRESETS, ForecastRequest

router = APIRouter(prefix="/cashflow", tags=["cashflow"])

PLACEHOLDER_NOTE = (
    "Start date, revenue run-rate and days-to-pay come from your invoice data. "
    "Starting cash, payroll, operating expenses, debt and one-time items are "
    "illustrative placeholders scaled to that revenue - replace them with your real numbers."
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
    derived = engine.default_assumptions(rows)
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


@router.post("/forecast")
def run_forecast(req: ForecastRequest):
    rows = ar.load_invoice_rows()
    return clean(engine.forecast(rows, req))


@router.post("/export")
def export_forecast(req: ForecastRequest, format: Literal["xlsx", "csv"] = "xlsx"):
    rows = ar.load_invoice_rows()
    result = engine.forecast(rows, req)
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
