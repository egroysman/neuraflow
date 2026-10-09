import datetime as dt
import io
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from cashflow import ar, engine
from cashflow.models import (
    Adjustments,
    Assumptions,
    Collections,
    Costs,
    ForecastRequest,
    General,
    Hire,
    Loan,
    OneTimeItem,
    OpexLine,
    Payroll,
    Sales,
)
from cashflow.router import router

D = dt.date


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


def inv(i, cust, invoice, terms, amount, paid=None):
    invoice_d = D.fromisoformat(invoice)
    due = invoice_d + dt.timedelta(days=terms)
    return {
        "InvoiceID": str(i),
        "CustomerID": cust,
        "InvoiceDate": invoice,
        "DueDate": due.isoformat(),
        "InvoiceAmount": str(amount),
        "PaymentDate": paid or "",
        "Status": "Paid" if paid else "Open",
        "OpenAmount": "0.0" if paid else str(amount),
        "TermsDays": str(terms),
    }


@pytest.fixture(scope="module")
def real_rows():
    return ar.load_invoice_rows()


@pytest.fixture(scope="module")
def defaults(real_rows):
    return engine.default_assumptions(real_rows)


@pytest.fixture
def base_assumptions():
    """A small, fully hand-checkable model with no receivables."""
    return Assumptions(
        general=General(as_of=D(2026, 1, 1), horizon_months=12, starting_cash=100_000, min_cash=20_000, tax_rate_pct=25),
        sales=Sales(monthly_revenue=100_000, growth_pct_monthly=0, dso_days=30, bad_debt_pct=0),
        costs=Costs(cogs_pct=40, dpo_days=30, opening_ap=0),
        payroll=Payroll(headcount=5, avg_salary=60_000, burden_pct=20, salary_growth_pct_annual=0),
        opex=[OpexLine(name="Rent", kind="fixed", amount=10_000)],
    )


# --------------------------------------------------------------------------- #
# Date helpers
# --------------------------------------------------------------------------- #


def test_add_months_clamps_to_month_end():
    assert engine.add_months(D(2026, 1, 31), 1) == D(2026, 2, 28)
    assert engine.add_months(D(2026, 1, 31), 2) == D(2026, 3, 31)
    assert engine.add_months(D(2026, 11, 15), 3) == D(2027, 2, 15)


# --------------------------------------------------------------------------- #
# Receivables projection
# --------------------------------------------------------------------------- #


def test_bucket_boundaries():
    assert ar.bucket_for(-5) == "current"
    assert ar.bucket_for(0) == "current"
    assert ar.bucket_for(1) == "d1_30"
    assert ar.bucket_for(30) == "d1_30"
    assert ar.bucket_for(31) == "d31_60"
    assert ar.bucket_for(90) == "d61_90"
    assert ar.bucket_for(91) == "d91_180"
    assert ar.bucket_for(181) == "d180_plus"


def test_projection_uses_customer_pattern_and_haircuts():
    rows = [
        # Customer A always pays 40 days after invoice (history).
        inv(1, "A", "2025-10-01", 30, 1000, "2025-11-10"),
        inv(2, "A", "2025-10-15", 30, 1000, "2025-11-24"),
        # Open invoice from A, not yet past its usual pattern.
        inv(3, "A", "2026-01-05", 30, 2000),
        # Open invoice that is very stale.
        inv(4, "B", "2025-06-01", 30, 500),
    ]
    invoices = ar.parse_invoices(rows)
    as_of = D(2026, 1, 10)
    projected = {p["invoice_id"]: p for p in ar.project_open_invoices(invoices, as_of, Collections())}
    # Pattern date = Jan 5 + 40 days = Feb 14.
    assert projected["3"]["expected_date"] == D(2026, 2, 14)
    assert projected["3"]["bucket"] == "current"
    assert projected["3"]["probability"] == pytest.approx(0.98)
    assert projected["3"]["expected_amount"] == pytest.approx(2000 * 0.98)
    # Stale invoice: far past due, collected later and heavily haircut.
    assert projected["4"]["bucket"] == "d180_plus"
    assert projected["4"]["probability"] == pytest.approx(0.40)
    assert projected["4"]["expected_date"] == as_of + dt.timedelta(days=120)


def test_projection_never_dates_before_start_even_with_negative_delay():
    invoices = ar.parse_invoices([inv(1, "A", "2025-12-01", 30, 1000)])
    projected = ar.project_open_invoices(invoices, D(2026, 1, 10), Collections(), delay_days=-60)
    assert projected[0]["expected_date"] >= D(2026, 1, 11)


def test_extra_bad_debt_scales_probability():
    invoices = ar.parse_invoices([inv(1, "A", "2026-01-05", 30, 1000)])
    p = ar.project_open_invoices(invoices, D(2026, 1, 10), Collections(), extra_bad_debt_pct=10)[0]
    assert p["probability"] == pytest.approx(0.98 * 0.9)


def test_open_invoices_at_is_point_in_time():
    invoices = ar.parse_invoices([inv(1, "A", "2026-01-01", 30, 1000, "2026-02-15")])
    assert len(ar.open_invoices_at(invoices, D(2026, 2, 1))) == 1  # not yet paid then
    assert len(ar.open_invoices_at(invoices, D(2026, 3, 1))) == 0  # paid by then
    assert len(ar.open_invoices_at(invoices, D(2025, 12, 15))) == 0  # not issued yet


def test_customer_stats_have_no_lookahead():
    invoices = ar.parse_invoices(
        [inv(1, "A", "2025-10-01", 30, 100, "2025-11-01"), inv(2, "A", "2025-12-01", 30, 100, "2026-03-01")]
    )
    stats = ar.customer_stats(invoices, D(2025, 12, 31))
    assert stats["A"]["paid_count"] == 1
    assert stats["A"]["avg_days_to_pay"] == 31


def test_calibration_learns_dead_invoices_and_stays_monotonic(real_rows):
    collections, meta = ar.calibrate_collections(ar.parse_invoices(real_rows))
    pct = collections.collectability_pct.model_dump()
    assert meta["calibrated"] and meta["snapshots"] >= 3
    values = [pct[b] for b in ar.BUCKETS]
    assert values == sorted(values, reverse=True), "worse buckets must not collect better"
    assert pct["d61_90"] == 0 and pct["d91_180"] == 0


def test_calibration_falls_back_with_thin_history():
    invoices = ar.parse_invoices([inv(1, "A", "2026-01-01", 30, 100, "2026-02-01")])
    collections, meta = ar.calibrate_collections(invoices)
    assert not meta["calibrated"]
    assert collections == Collections()


def test_backtest_projection_tracks_actual_collections(real_rows):
    """Projected 60-day collections should land close to what was actually paid."""
    invoices = ar.parse_invoices(real_rows)
    as_of = D(2026, 4, 9)
    collections, _ = ar.calibrate_collections(invoices)
    projected = ar.project_open_invoices(invoices, as_of, collections)
    cutoff = as_of + dt.timedelta(days=60)
    predicted = sum(p["expected_amount"] for p in projected if p["expected_date"] <= cutoff)
    by_id = {i.invoice_id: i for i in invoices}
    actual = sum(
        by_id[p["invoice_id"]].amount
        for p in projected
        if by_id[p["invoice_id"]].payment_date and by_id[p["invoice_id"]].payment_date <= cutoff
    )
    assert actual > 0
    assert 0.85 <= predicted / actual <= 1.15


# --------------------------------------------------------------------------- #
# Engine: reconciliation and cash roll
# --------------------------------------------------------------------------- #


def run(rows, assumptions, scenario="base", adjustments=None):
    return engine.forecast(rows, ForecastRequest(assumptions=assumptions, scenario=scenario, adjustments=adjustments or Adjustments()))


def test_statement_reconciles_to_events(real_rows, defaults):
    a = defaults["assumptions"]
    invoices = ar.parse_invoices(real_rows)
    model = engine.run_model(invoices, a, Adjustments())
    start = a.general.as_of
    end = model.horizon_end
    total_events = sum(e.amount for e in model.events if start <= e.date < end)
    assert sum(p["net"] for p in model.monthly) == pytest.approx(total_events)
    assert model.monthly[-1]["end_cash"] == pytest.approx(a.general.starting_cash + total_events)
    weekly_end = start + dt.timedelta(days=7 * engine.WEEKS)
    weekly_events = sum(e.amount for e in model.events if start <= e.date < weekly_end)
    assert sum(p["net"] for p in model.weekly) == pytest.approx(weekly_events)


def test_cash_rolls_forward_without_gaps(real_rows, defaults):
    result = run(real_rows, defaults["assumptions"])
    for series in (result["monthly"], result["weekly"]):
        assert series[0]["begin_cash"] == pytest.approx(defaults["assumptions"].general.starting_cash)
        for prev, cur in zip(series, series[1:]):
            assert cur["begin_cash"] == pytest.approx(prev["end_cash"])
            assert cur["start"] == prev["end"]
        for p in series:
            assert p["end_cash"] == pytest.approx(p["begin_cash"] + p["net"])
            assert p["net"] == pytest.approx(p["operating"] + p["investing"] + p["financing"])
            assert sum(p["categories"].values()) == pytest.approx(p["net"])


def test_hand_checked_operating_month(base_assumptions):
    """No receivables: month 1 has payroll, rent, opening-free vendor payments only."""
    result = run([], base_assumptions)
    m0 = result["monthly"][0]["categories"]
    # 5 heads x 60k / 12 x 1.2 = 30,000 payroll.
    assert m0["payroll"] == pytest.approx(-30_000)
    assert m0["opex"] == pytest.approx(-10_000)
    # Sales are invoiced on day 14 (Jan 15) and collected 25% / 50% / 25% on
    # days dso-15, dso, dso+15 after that: Jan 30, Feb 14, Mar 1.
    assert m0["new_sales_collections"] == pytest.approx(25_000)
    m1 = result["monthly"][1]["categories"]
    assert m1["new_sales_collections"] == pytest.approx(50_000)
    # Vendor cost (40k) is paid dpo=30 days after invoicing: Feb 14.
    assert m0["cogs_vendors"] == pytest.approx(0, abs=1e-6)
    assert m1["cogs_vendors"] == pytest.approx(-40_000)
    # 1.2M invoiced over the year; month 11's last 75% lands after the horizon.
    total_new_sales = sum(p["categories"]["new_sales_collections"] for p in result["monthly"])
    assert total_new_sales == pytest.approx(1_125_000)


def test_growth_compounds_monthly(base_assumptions):
    base_assumptions.sales.growth_pct_monthly = 10
    result = run([], base_assumptions)
    revenue = [p["revenue"] for p in result["pnl"]]
    assert revenue[1] == pytest.approx(revenue[0] * 1.10)
    assert revenue[11] == pytest.approx(revenue[0] * 1.10 ** 11)


def test_hiring_plan_raises_payroll(base_assumptions):
    base_assumptions.payroll.hires = [Hire(month=3, count=2)]
    result = run([], base_assumptions)
    payroll = [p["payroll"] for p in result["pnl"]]
    assert payroll[2] == pytest.approx(30_000)
    assert payroll[3] == pytest.approx(7 * 60_000 / 12 * 1.2)


def test_pct_revenue_opex_and_line_windows(base_assumptions):
    base_assumptions.opex = [
        OpexLine(name="Marketing", kind="pct_revenue", amount=5),
        OpexLine(name="Pilot", kind="fixed", amount=7_000, start_month=2, end_month=4),
    ]
    result = run([], base_assumptions)
    opex = [p["opex"] for p in result["pnl"]]
    assert opex[0] == pytest.approx(5_000)  # 5% of 100k, pilot not started
    assert opex[2] == pytest.approx(12_000)
    assert opex[4] == pytest.approx(12_000)
    assert opex[5] == pytest.approx(5_000)  # pilot ended


def test_loan_amortizes_and_stops_at_zero(base_assumptions):
    base_assumptions.loans = [Loan(name="Note", balance=10_000, annual_rate_pct=12, monthly_payment=4_000)]
    result = run([], base_assumptions)
    payments = [-p["categories"]["debt_service"] for p in result["monthly"]]
    interest = [p["interest"] for p in result["pnl"]]
    assert payments[0] == pytest.approx(4_000)
    assert interest[0] == pytest.approx(10_000 * 0.01)
    assert payments[2] < 4_000  # final partial payment
    assert all(p == 0 for p in payments[3:])
    # Principal repaid equals the starting balance.
    principal = sum(payments) - sum(interest)
    assert principal == pytest.approx(10_000)


def test_taxes_only_on_profitable_quarters(base_assumptions):
    profitable = run([], base_assumptions)
    taxes = [p["categories"]["taxes"] for p in profitable["monthly"]]
    assert any(t < 0 for t in taxes)
    assert all(t <= 0 for t in taxes)

    base_assumptions.costs.cogs_pct = 95
    loss_making = run([], base_assumptions)
    assert all(p["categories"]["taxes"] == 0 for p in loss_making["monthly"])


def test_one_time_items_land_in_the_right_section_and_window(base_assumptions):
    base_assumptions.one_time = [
        OneTimeItem(name="Equipment", date=D(2026, 3, 10), amount=-25_000, category="investing"),
        OneTimeItem(name="Equity raise", date=D(2026, 5, 1), amount=200_000, category="financing"),
        OneTimeItem(name="Refund", date=D(2026, 6, 1), amount=5_000, category="operating"),
        OneTimeItem(name="Too late", date=D(2030, 1, 1), amount=-999_999, category="investing"),
        OneTimeItem(name="Before start", date=D(2025, 12, 31), amount=-999_999, category="investing"),
    ]
    result = run([], base_assumptions)
    assert sum(p["investing"] for p in result["monthly"]) == pytest.approx(-25_000)
    assert sum(p["categories"]["financing_other"] for p in result["monthly"]) == pytest.approx(200_000)
    assert sum(p["categories"]["other_operating"] for p in result["monthly"]) == pytest.approx(5_000)


def test_opening_payables_are_paid_early(base_assumptions):
    base_assumptions.costs.opening_ap = 35_000
    result = run([], base_assumptions)
    first_two_weeks = sum(p["categories"]["cogs_vendors"] for p in result["weekly"][:5])
    assert first_two_weeks == pytest.approx(-35_000)


# --------------------------------------------------------------------------- #
# Scenarios and what-if
# --------------------------------------------------------------------------- #


def test_scenarios_are_ordered(real_rows, defaults):
    result = run(real_rows, defaults["assumptions"])
    c = result["comparison"]
    assert c["worst"]["ending_cash"] < c["base"]["ending_cash"] < c["best"]["ending_cash"]
    assert c["worst"]["lowest_balance"] < c["base"]["lowest_balance"] < c["best"]["lowest_balance"]
    assert c["base"]["monthly_end_cash"][-1] == pytest.approx(result["kpis"]["monthly"]["ending_cash"])


def test_selecting_a_scenario_switches_the_headline(real_rows, defaults):
    a = defaults["assumptions"]
    base = run(real_rows, a, "base")
    worst = run(real_rows, a, "worst")
    assert worst["kpis"]["monthly"]["ending_cash"] < base["kpis"]["monthly"]["ending_cash"]
    assert worst["comparison"]["worst"]["ending_cash"] == pytest.approx(worst["kpis"]["monthly"]["ending_cash"])
    # The comparison always contains all three regardless of which is selected.
    assert set(worst["comparison"]) == {"base", "best", "worst"}


@pytest.mark.parametrize(
    "field,value,direction",
    [
        ("collection_delay_days", 30, -1),
        ("extra_bad_debt_pct", 10, -1),
        ("revenue_change_pct", 20, +1),
        ("growth_change_pct_pts", 2, +1),
        ("cogs_change_pct_pts", 5, -1),
        ("opex_change_pct", 20, -1),
        ("dpo_change_days", -20, -1),
    ],
)
def test_each_adjustment_moves_cash_the_right_way(real_rows, defaults, field, value, direction):
    a = defaults["assumptions"]
    base = run(real_rows, a)["kpis"]["monthly"]["ending_cash"]
    moved = run(real_rows, a, adjustments=Adjustments(**{field: value}))["kpis"]["monthly"]["ending_cash"]
    assert (moved - base) * direction > 0


def test_user_adjustments_stack_on_top_of_preset(real_rows, defaults):
    a = defaults["assumptions"]
    result = run(real_rows, a, "worst", Adjustments(collection_delay_days=10))
    assert result["effective_adjustments"]["collection_delay_days"] == 21 + 10


def test_assumptions_are_not_mutated_by_scenarios(real_rows, defaults):
    a = defaults["assumptions"]
    before = a.model_dump()
    run(real_rows, a, "worst", Adjustments(opex_change_pct=40))
    assert a.model_dump() == before


# --------------------------------------------------------------------------- #
# KPIs and alerts
# --------------------------------------------------------------------------- #


def test_daily_low_point_and_runway_when_cash_runs_out(base_assumptions):
    base_assumptions.general.starting_cash = 5_000
    base_assumptions.general.min_cash = 50_000
    result = run([], base_assumptions)
    kpis = result["kpis"]["monthly"]
    assert kpis["lowest_balance"] < 0
    assert kpis["first_negative_date"] is not None
    assert kpis["runway_months"] is not None and kpis["runway_months"] < 2
    assert kpis["funding_gap"] == pytest.approx(50_000 - kpis["lowest_balance"])
    assert result["alerts"] and result["alerts"][0]["level"] == "danger"


def test_below_minimum_warning_without_going_negative(base_assumptions):
    base_assumptions.general.starting_cash = 100_000
    base_assumptions.general.min_cash = 99_000
    result = run([], base_assumptions)
    kpis = result["kpis"]["monthly"]
    assert kpis["first_negative_date"] is None
    assert kpis["first_below_min_date"] is not None
    assert result["alerts"][0]["level"] == "warning"


def test_no_alerts_when_comfortably_funded(base_assumptions):
    base_assumptions.general.starting_cash = 5_000_000
    base_assumptions.general.min_cash = 1_000
    assert run([], base_assumptions)["alerts"] == []


# --------------------------------------------------------------------------- #
# Defaults derived from data
# --------------------------------------------------------------------------- #


def test_defaults_come_from_the_invoice_data(real_rows, defaults):
    summary = defaults["data_summary"]
    a = defaults["assumptions"]
    assert summary["as_of"] == D(2026, 4, 9)  # newest invoice date
    assert a.general.as_of == summary["as_of"]
    assert 300_000 < a.sales.monthly_revenue < 400_000
    assert 55 <= a.sales.dso_days <= 70
    assert summary["customer_count"] == 25
    assert summary["open_ar"] > 0


def test_defaults_work_with_no_data():
    derived = engine.default_assumptions([], today=D(2026, 10, 8))
    a = derived["assumptions"]
    assert a.general.as_of == D(2026, 10, 8)
    result = engine.forecast([], ForecastRequest(assumptions=a))
    assert len(result["monthly"]) == 12 and result["ar"]["open_total"] == 0


def test_malformed_rows_are_skipped():
    rows = [
        {"InvoiceID": "1", "CustomerID": "", "InvoiceDate": "2026-01-01", "InvoiceAmount": "100"},
        {"InvoiceID": "2", "CustomerID": "A", "InvoiceDate": "not-a-date", "InvoiceAmount": "100"},
        {"InvoiceID": "3", "CustomerID": "A", "InvoiceDate": "2026-01-01", "InvoiceAmount": "-5"},
        inv(4, "A", "2026-01-01", 30, 100),
    ]
    assert len(ar.parse_invoices(rows)) == 1


# --------------------------------------------------------------------------- #
# HTTP API
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_api_defaults_then_forecast_round_trip(client):
    d = client.get("/cashflow/defaults")
    assert d.status_code == 200
    body = d.json()
    assert set(body["scenarios"]) == {"base", "best", "worst"}
    assert body["data_summary"]["as_of"] == "2026-04-09"
    assert "placeholder" in body["note"]

    r = client.post("/cashflow/forecast", json={"assumptions": body["assumptions"], "scenario": "worst"})
    assert r.status_code == 200
    out = r.json()
    assert out["scenario"] == "worst"
    assert len(out["monthly"]) == 12 and len(out["weekly"]) == 13
    assert out["monthly"][0]["start"] == "2026-04-09"
    assert {c["section"] for c in out["categories"]} == {"operating", "investing", "financing"}


def test_api_rejects_invalid_input(client):
    a = client.get("/cashflow/defaults").json()["assumptions"]
    a["general"]["horizon_months"] = 99
    assert client.post("/cashflow/forecast", json={"assumptions": a}).status_code == 422
    a["general"]["horizon_months"] = 12
    a["sales"]["dso_days"] = -1
    assert client.post("/cashflow/forecast", json={"assumptions": a}).status_code == 422
    a["sales"]["dso_days"] = 30
    assert client.post("/cashflow/forecast", json={"assumptions": a, "scenario": "bogus"}).status_code == 422


def test_api_csv_export(client):
    a = client.get("/cashflow/defaults").json()["assumptions"]
    r = client.post("/cashflow/export?format=csv", json={"assumptions": a})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"] and ".csv" in r.headers["content-disposition"]
    lines = r.text.strip().splitlines()
    assert len(lines) == 13  # header + 12 months
    assert lines[0].startswith("period,start,end")


def test_api_xlsx_export_has_expected_sheets(client):
    a = client.get("/cashflow/defaults").json()["assumptions"]
    r = client.post("/cashflow/export?format=xlsx", json={"assumptions": a, "scenario": "best"})
    assert r.status_code == 200
    wb = load_workbook(io.BytesIO(r.content))
    assert wb.sheetnames == ["Summary", "Projections", "Monthly", "13-Week", "P&L", "Scenarios", "Receivables", "Credit Scores", "Payables", "Capex", "Payroll", "Balance Sheet", "GL vs Forecast", "Assumptions"]
    assert wb["Summary"]["B3"].value == "Best case"


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice not installed")
def test_excel_formulas_recalculate_to_the_engine_numbers(real_rows, defaults, tmp_path):
    """Open the exported workbook in LibreOffice and compare its recalculated
    ending cash and net cash flow with the engine, for both statements."""
    a = defaults["assumptions"]
    req = ForecastRequest(assumptions=a, scenario="worst", adjustments=Adjustments(collection_delay_days=5))
    result = engine.forecast(real_rows, req)
    from cashflow import export

    src = tmp_path / "model.xlsx"
    src.write_bytes(export.build_xlsx(result, a))
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    subprocess.run(
        ["soffice", "--headless", "--calc", "--convert-to", "xlsx", "--outdir", str(out_dir), str(src)],
        check=True, capture_output=True, timeout=180,
    )
    wb = load_workbook(out_dir / "model.xlsx", data_only=True)
    for sheet, key in (("Monthly", "monthly"), ("13-Week", "weekly")):
        ws = wb[sheet]
        labels = {ws.cell(row=r, column=1).value: r for r in range(1, ws.max_row + 1)}
        for i, period in enumerate(result[key]):
            col = 2 + i
            assert ws.cell(row=labels["NET CASH FLOW"], column=col).value == pytest.approx(period["net"], abs=0.01 * 100)
            assert ws.cell(row=labels["ENDING CASH"], column=col).value == pytest.approx(period["end_cash"], abs=1.0 + 0.5 * (i + 1))
    pnl = wb["P&L"]
    first_pretax = result["pnl"][0]["pretax_profit"]
    assert pnl.cell(row=11, column=2).value == pytest.approx(first_pretax, abs=0.5)
