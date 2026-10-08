"""Excel and CSV export.

The workbook keeps inputs as values and writes subtotals, net cash flow and the
running cash balance as live formulas, so the statements stay editable in Excel.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Any, Dict, List

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from .engine import CATEGORIES, SECTIONS
from .models import Assumptions

MONEY = '#,##0;[Red](#,##0);"-"'
PCT = "0.0%"
DATE = "yyyy-mm-dd"
HEADER_FILL = PatternFill("solid", fgColor="1F2937")
SECTION_FILL = PatternFill("solid", fgColor="E5E7EB")
TOTAL_FILL = PatternFill("solid", fgColor="DBEAFE")
HEADER_FONT = Font(bold=True, color="FFFFFF")
BOLD = Font(bold=True)
THIN = Side(style="thin", color="9CA3AF")


def _header(ws, row: int, values: List[Any], start_col: int = 1) -> None:
    for i, value in enumerate(values):
        cell = ws.cell(row=row, column=start_col + i, value=value)
        cell.font = HEADER_FONT
        cell.fill = HEADER_FILL
        cell.alignment = Alignment(horizontal="center" if i else "left")


def _widths(ws, first: float, rest: float, columns: int) -> None:
    ws.column_dimensions["A"].width = first
    for col in range(2, columns + 1):
        ws.column_dimensions[get_column_letter(col)].width = rest


def _statement(ws, title: str, periods: List[Dict[str, Any]], starting_cash: float, min_cash: float) -> None:
    ncols = len(periods)
    ws["A1"] = title
    ws["A1"].font = Font(bold=True, size=14)
    _header(ws, 3, ["Cash flow (USD)"] + [p["label"] for p in periods])
    ws.cell(row=4, column=1, value="Period start").font = Font(italic=True)
    ws.cell(row=5, column=1, value="Period end (exclusive)").font = Font(italic=True)
    for i, p in enumerate(periods):
        for r, key in ((4, "start"), (5, "end")):
            cell = ws.cell(row=r, column=2 + i, value=p[key])
            cell.number_format = DATE
            cell.font = Font(italic=True)
            cell.alignment = Alignment(horizontal="center")

    row = 7
    section_rows: Dict[str, int] = {}
    for section in SECTIONS:
        ws.cell(row=row, column=1, value=section.upper() + " ACTIVITIES").font = BOLD
        for col in range(1, ncols + 2):
            ws.cell(row=row, column=col).fill = SECTION_FILL
        row += 1
        first = row
        for key, label, sec in CATEGORIES:
            if sec != section:
                continue
            ws.cell(row=row, column=1, value=label)
            for i, p in enumerate(periods):
                cell = ws.cell(row=row, column=2 + i, value=round(p["categories"][key], 2))
                cell.number_format = MONEY
            row += 1
        last = row - 1
        ws.cell(row=row, column=1, value=f"Net {section} cash flow").font = BOLD
        for i in range(ncols):
            col = get_column_letter(2 + i)
            cell = ws.cell(row=row, column=2 + i, value=f"=SUM({col}{first}:{col}{last})")
            cell.number_format = MONEY
            cell.font = BOLD
            cell.border = Border(top=THIN)
        section_rows[section] = row
        row += 2

    net_row = row
    ws.cell(row=net_row, column=1, value="NET CASH FLOW").font = BOLD
    begin_row, end_row, min_row, flag_row = net_row + 2, net_row + 3, net_row + 4, net_row + 5
    ws.cell(row=begin_row, column=1, value="Beginning cash")
    ws.cell(row=end_row, column=1, value="ENDING CASH").font = BOLD
    ws.cell(row=min_row, column=1, value="Minimum cash target")
    ws.cell(row=flag_row, column=1, value="Below minimum?")
    for i in range(ncols):
        col = get_column_letter(2 + i)
        prev = get_column_letter(1 + i)
        net = ws.cell(
            row=net_row,
            column=2 + i,
            value="=" + "+".join(f"{col}{section_rows[s]}" for s in SECTIONS),
        )
        net.number_format = MONEY
        net.font = BOLD
        net.fill = TOTAL_FILL
        begin = ws.cell(
            row=begin_row,
            column=2 + i,
            value=round(starting_cash, 2) if i == 0 else f"={prev}{end_row}",
        )
        begin.number_format = MONEY
        end = ws.cell(row=end_row, column=2 + i, value=f"={col}{begin_row}+{col}{net_row}")
        end.number_format = MONEY
        end.font = BOLD
        end.fill = TOTAL_FILL
        end.border = Border(top=THIN, bottom=THIN)
        minimum = ws.cell(row=min_row, column=2 + i, value=round(min_cash, 2))
        minimum.number_format = MONEY
        ws.cell(row=flag_row, column=2 + i, value=f'=IF({col}{end_row}<{col}{min_row},"YES","")').alignment = Alignment(horizontal="center")
    ws.cell(row=net_row, column=1).fill = TOTAL_FILL
    ws.cell(row=end_row, column=1).fill = TOTAL_FILL
    ws.freeze_panes = "B6"
    _widths(ws, 38, 14, ncols + 1)


def _pnl(ws, pnl: List[Dict[str, Any]]) -> None:
    ws["A1"] = "Monthly profit & loss (accrual basis, before income tax)"
    ws["A1"].font = Font(bold=True, size=14)
    _header(ws, 3, ["USD"] + [p["label"] for p in pnl])
    lines = [
        ("Revenue", "revenue"),
        ("Cost of sales", "cogs"),
        ("Gross profit", None),
        ("Payroll & benefits", "payroll"),
        ("Operating expenses", "opex"),
        ("Interest expense", "interest"),
        ("Pre-tax profit", None),
    ]
    for r, (label, key) in enumerate(lines, start=4):
        ws.cell(row=r, column=1, value=label)
        for i, p in enumerate(pnl):
            col = get_column_letter(2 + i)
            if key:
                value: Any = round(p[key], 2)
            elif label == "Gross profit":
                value = f"={col}4-{col}5"
            else:
                value = f"={col}6-{col}7-{col}8-{col}9"
            cell = ws.cell(row=r, column=2 + i, value=value)
            cell.number_format = MONEY
            if not key:
                cell.font = BOLD
                cell.fill = TOTAL_FILL
        if not key:
            ws.cell(row=r, column=1).font = BOLD
            ws.cell(row=r, column=1).fill = TOTAL_FILL
    _widths(ws, 30, 13, len(pnl) + 1)
    ws.freeze_panes = "B4"


def _assumptions(ws, a: Assumptions) -> None:
    ws["A1"] = "Assumptions"
    ws["A1"].font = Font(bold=True, size=14)
    data = a.model_dump(mode="json")
    row = 3
    for section in ("general", "sales", "costs"):
        ws.cell(row=row, column=1, value=section.title()).font = BOLD
        row += 1
        for key, value in data[section].items():
            ws.cell(row=row, column=1, value=key.replace("_", " "))
            ws.cell(row=row, column=2, value=value)
            row += 1
        row += 1
    ws.cell(row=row, column=1, value="Payroll").font = BOLD
    row += 1
    for key, value in data["payroll"].items():
        if key == "hires":
            continue
        ws.cell(row=row, column=1, value=key.replace("_", " "))
        ws.cell(row=row, column=2, value=value)
        row += 1
    row += 1
    ws.cell(row=row, column=1, value="Receivable collectability (%) and overdue lag (days), by aging").font = BOLD
    row += 1
    _header(ws, row, ["Bucket", "Collectability %", "Lag days"])
    row += 1
    for bucket, pct in data["collections"]["collectability_pct"].items():
        ws.cell(row=row, column=1, value=bucket)
        ws.cell(row=row, column=2, value=pct)
        ws.cell(row=row, column=3, value=data["collections"]["overdue_lag_days"][bucket])
        row += 1
    row += 1

    def table(title: str, headers: List[str], items: List[List[Any]]) -> None:
        nonlocal row
        ws.cell(row=row, column=1, value=title).font = BOLD
        row += 1
        _header(ws, row, headers)
        row += 1
        for item in items:
            for col, value in enumerate(item, start=1):
                ws.cell(row=row, column=col, value=value)
            row += 1
        row += 1

    table("Hiring plan", ["Month #", "Heads"], [[h["month"], h["count"]] for h in data["payroll"]["hires"]])
    table(
        "Operating expense lines",
        ["Name", "Kind", "Amount", "Growth %/mo", "Start month", "End month"],
        [[o["name"], o["kind"], o["amount"], o["growth_pct_monthly"], o["start_month"], o["end_month"]] for o in data["opex"]],
    )
    table(
        "Loans",
        ["Name", "Balance", "Rate %", "Monthly payment"],
        [[l["name"], l["balance"], l["annual_rate_pct"], l["monthly_payment"]] for l in data["loans"]],
    )
    table(
        "One-time items",
        ["Name", "Date", "Amount", "Category"],
        [[o["name"], o["date"], o["amount"], o["category"]] for o in data["one_time"]],
    )
    _widths(ws, 34, 18, 6)


def _ar(ws, ar_data: Dict[str, Any]) -> None:
    ws["A1"] = "Receivables outlook"
    ws["A1"].font = Font(bold=True, size=14)
    ws["A3"], ws["B3"] = "Open receivables", round(ar_data["open_total"], 2)
    ws["A4"], ws["B4"] = "Expected to collect (after haircuts)", round(ar_data["expected_total"], 2)
    ws["A5"], ws["B5"] = "Expected within the forecast horizon", round(ar_data["expected_in_horizon"], 2)
    for r in (3, 4, 5):
        ws.cell(row=r, column=2).number_format = MONEY

    _header(ws, 7, ["Aging bucket", "Open amount", "Invoices"])
    row = 8
    for item in ar_data["aging"]:
        ws.cell(row=row, column=1, value=item["label"])
        c = ws.cell(row=row, column=2, value=round(item["open_amount"], 2))
        c.number_format = MONEY
        ws.cell(row=row, column=3, value=item["invoices"])
        row += 1

    row += 1
    _header(
        ws, row,
        ["Customer", "Open invoices", "Open amount", "Expected in horizon", "Avg days to pay", "Oldest days past due", "Risk"],
    )
    row += 1
    for cust in ar_data["customers"]:
        values = [
            cust["customer_id"], cust["open_invoices"], round(cust["open_amount"], 2),
            round(cust["expected_in_horizon"], 2),
            None if cust["avg_days_to_pay"] is None else round(cust["avg_days_to_pay"], 1),
            cust["oldest_days_past_due"], cust["risk"],
        ]
        for col, value in enumerate(values, start=1):
            cell = ws.cell(row=row, column=col, value=value)
            if col in (3, 4):
                cell.number_format = MONEY
        row += 1
    _widths(ws, 36, 20, 7)


def _scenarios(ws, result: Dict[str, Any]) -> None:
    ws["A1"] = "Scenario comparison: ending cash by month"
    ws["A1"].font = Font(bold=True, size=14)
    labels = [p["label"] for p in result["monthly"]]
    _header(ws, 3, ["Scenario"] + labels)
    for r, (name, data) in enumerate(result["comparison"].items(), start=4):
        ws.cell(row=r, column=1, value=data["label"])
        for i, value in enumerate(data["monthly_end_cash"]):
            cell = ws.cell(row=r, column=2 + i, value=round(value, 2))
            cell.number_format = MONEY
    _widths(ws, 24, 14, len(labels) + 1)


def _summary(ws, result: Dict[str, Any], assumptions: Assumptions) -> None:
    k = result["kpis"]["monthly"]
    ws["A1"] = "NeuraFlow cash flow model"
    ws["A1"].font = Font(bold=True, size=16)
    rows = [
        ("Scenario", result["scenario_label"]),
        ("Forecast start", result["as_of"]),
        ("Forecast end", result["horizon_end"]),
        ("Starting cash", round(k["starting_cash"], 2)),
        ("Ending cash", round(k["ending_cash"], 2)),
        ("Net cash flow", round(k["net_cash_flow"], 2)),
        ("Operating cash flow", round(k["operating_cash_flow"], 2)),
        ("Investing cash flow", round(k["investing_cash_flow"], 2)),
        ("Financing cash flow", round(k["financing_cash_flow"], 2)),
        ("Lowest balance", round(k["lowest_balance"], 2)),
        ("Lowest balance date", k["lowest_balance_date"]),
        ("Minimum cash target", round(assumptions.general.min_cash, 2)),
        ("Funding gap vs minimum", round(k["funding_gap"], 2)),
        ("Runway (months)", k["runway_months"] if k["runway_months"] is not None else "Cash stays positive"),
    ]
    for r, (label, value) in enumerate(rows, start=3):
        ws.cell(row=r, column=1, value=label).font = BOLD
        cell = ws.cell(row=r, column=2, value=value)
        if isinstance(value, dt.date):
            cell.number_format = DATE
        elif isinstance(value, float):
            cell.number_format = MONEY
    r = 3 + len(rows) + 1
    ws.cell(row=r, column=1, value="Scenario adjustments applied").font = BOLD
    r += 1
    for key, value in result["effective_adjustments"].items():
        ws.cell(row=r, column=1, value=key.replace("_", " "))
        ws.cell(row=r, column=2, value=value)
        r += 1
    r += 1
    ws.cell(row=r, column=1, value="Alerts").font = BOLD
    r += 1
    for alert in result["alerts"] or [{"message": "None"}]:
        ws.cell(row=r, column=1, value=alert["message"])
        r += 1
    r += 1
    ws.cell(
        row=r,
        column=1,
        value="Receivables come from the invoice data. Payroll, opex, debt and one-off items are only as good as the assumptions entered.",
    ).font = Font(italic=True)
    _widths(ws, 34, 24, 2)


def build_xlsx(result: Dict[str, Any], assumptions: Assumptions) -> bytes:
    wb = Workbook()
    _summary(wb.active, result, assumptions)
    wb.active.title = "Summary"
    g = assumptions.general
    _statement(wb.create_sheet("Monthly"), "Monthly cash flow statement", result["monthly"], g.starting_cash, g.min_cash)
    _statement(wb.create_sheet("13-Week"), "13-week cash flow", result["weekly"], g.starting_cash, g.min_cash)
    _pnl(wb.create_sheet("P&L"), result["pnl"])
    _scenarios(wb.create_sheet("Scenarios"), result)
    _ar(wb.create_sheet("Receivables"), result["ar"])
    _assumptions(wb.create_sheet("Assumptions"), assumptions)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


def build_csv(result: Dict[str, Any]) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    keys = [c[0] for c in CATEGORIES]
    labels = [c[1] for c in CATEGORIES]
    writer.writerow(
        ["period", "start", "end"] + labels
        + ["operating", "investing", "financing", "net_cash_flow", "beginning_cash", "ending_cash"]
    )
    for p in result["monthly"]:
        writer.writerow(
            [p["label"], p["start"].isoformat(), p["end"].isoformat()]
            + [round(p["categories"][k], 2) for k in keys]
            + [round(p[x], 2) for x in ("operating", "investing", "financing", "net", "begin_cash", "end_cash")]
        )
    return buffer.getvalue()
