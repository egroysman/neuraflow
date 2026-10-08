"""Tests for payables, capex, trends and the macro overlay."""
import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cashflow import ap, ar, capex, engine, macro, trends
from cashflow.models import (
    AP,
    Adjustments,
    Assumptions,
    Capex,
    CapexItem,
    Costs,
    ForecastRequest,
    General,
    Loan,
    Macro,
    OpexLine,
    Payroll,
    Sales,
)
from cashflow.router import router

D = dt.date


def bill(i, vendor, bill_date, terms, amount, paid=None, category="Cost of sales"):
    bd = D.fromisoformat(bill_date)
    return {
        "BillID": str(i), "VendorID": vendor, "VendorName": f"Vendor {vendor}", "Category": category,
        "BillDate": bill_date, "DueDate": (bd + dt.timedelta(days=terms)).isoformat(),
        "BillAmount": str(amount), "PaymentDate": paid or "", "Status": "Paid" if paid else "Open",
        "OpenAmount": "0.0" if paid else str(amount), "TermsDays": str(terms),
    }


@pytest.fixture
def blank():
    """No revenue, no payroll: only what a test adds shows up in the cash flow."""
    return Assumptions(
        general=General(as_of=D(2026, 1, 1), horizon_months=12, starting_cash=1_000_000, min_cash=0, tax_rate_pct=0),
        sales=Sales(monthly_revenue=0),
        costs=Costs(cogs_pct=0, dpo_days=30, opening_ap=0),
        payroll=Payroll(headcount=0),
    )


def run(a, adj=None, bills=None):
    return engine.run_model([], a, adj or Adjustments(), ap.parse_bills(bills) if bills else None)


def total(model, category):
    return sum(p["categories"][category] for p in model.monthly)


# --------------------------------------------------------------------------- #
# Payables
# --------------------------------------------------------------------------- #

AS_OF = D(2026, 1, 1)
BILLS = [
    bill(1, "A", "2025-10-01", 30, 1000, paid="2025-11-05"),   # paid 5 days late
    bill(2, "A", "2025-11-01", 30, 1000, paid="2025-12-11"),   # paid 10 days late
    bill(3, "B", "2025-12-20", 30, 4000),                       # open, due 2026-01-19
    bill(4, "B", "2025-11-01", 30, 2500),                       # open, due 2025-12-01: 31 days past due
    bill(5, "C", "2025-12-30", 60, 800, paid="2026-02-01"),     # paid after the start date: still open then
    bill(6, "C", "2026-02-01", 30, 9999),                       # dated after the start: ignored
]


def test_open_bills_at_includes_bills_paid_after_the_start_date_only():
    bills = ap.parse_bills(BILLS)
    ids = sorted(b.bill_id for b in ap.open_bills_at(bills, AS_OF))
    assert ids == ["3", "4", "5"]


def test_vendor_habits_use_only_payments_before_the_start_date():
    bills = ap.parse_bills(BILLS)
    stats = ap.vendor_stats(bills, AS_OF)
    assert stats["A"]["avg_days_vs_due"] == pytest.approx(7.5)
    assert "C" not in stats  # its only payment is after the start date
    assert ap.typical_lag_days(bills, AS_OF) == pytest.approx(7.5)


def test_projection_pays_on_due_date_plus_lag_and_clears_overdue_quickly():
    bills = ap.parse_bills(BILLS)
    p = {x["bill_id"]: x for x in ap.project_open_bills(bills, AS_OF, payment_lag_days=3, overdue_catchup_days=14)}
    assert p["3"]["expected_date"] == D(2026, 1, 22)   # due Jan 19 + 3 days
    assert p["5"]["expected_date"] == D(2026, 3, 3)    # due Feb 28 + 3 days
    assert p["4"]["days_past_due"] == 31 and p["4"]["bucket"] == "d31_60"
    assert p["4"]["expected_date"] == D(2026, 1, 12)   # overdue: inside the 14-day catch-up window
    assert all(x["expected_date"] > AS_OF for x in p.values())


def test_scenario_dpo_stretch_delays_payments():
    bills = ap.parse_bills(BILLS)
    base = {x["bill_id"]: x["expected_date"] for x in ap.project_open_bills(bills, AS_OF)}
    slow = {x["bill_id"]: x["expected_date"] for x in ap.project_open_bills(bills, AS_OF, dpo_change_days=10)}
    assert slow["3"] == base["3"] + dt.timedelta(days=10)


def test_ap_aging_and_summary_reconcile():
    bills = ap.parse_bills(BILLS)
    projected = ap.project_open_bills(bills, AS_OF)
    summary = ap.summarize_ap(bills, projected, AS_OF, D(2027, 1, 1))
    assert summary["open_total"] == pytest.approx(4000 + 2500 + 800)
    assert sum(r["open_amount"] for r in summary["aging"]) == pytest.approx(summary["open_total"])
    assert summary["overdue_total"] == pytest.approx(2500)
    assert sum(v["open_amount"] for v in summary["vendors"]) == pytest.approx(summary["open_total"])
    assert sum(m["amount"] for m in summary["due_by_month"]) == pytest.approx(summary["open_total"])


def test_open_bills_flow_into_the_forecast_instead_of_the_lump(blank):
    blank.costs.opening_ap = 50_000
    with_bills = run(blank, bills=BILLS)
    assert total(with_bills, "ap_open_bills") == pytest.approx(-(4000 + 2500 + 800))
    assert total(with_bills, "cogs_vendors") == pytest.approx(0)  # lump replaced, not added
    blank.ap = AP(use_open_bills=False)
    lump = run(blank, bills=BILLS)
    assert total(lump, "ap_open_bills") == 0
    assert total(lump, "cogs_vendors") == pytest.approx(-50_000)


def test_without_any_bills_the_lump_is_used(blank):
    blank.costs.opening_ap = 20_000
    model = run(blank)
    assert total(model, "cogs_vendors") == pytest.approx(-20_000)


# --------------------------------------------------------------------------- #
# Capex
# --------------------------------------------------------------------------- #


def item(**kw):
    base = dict(name="Machine", date=D(2026, 3, 15), amount=120_000, kind="growth", funding="cash", useful_life_months=60)
    base.update(kw)
    return CapexItem(**base)


def test_pmt_matches_the_textbook_formula():
    assert capex.pmt(100_000, 0, 10) == pytest.approx(10_000)
    assert capex.pmt(100_000, 12, 12) == pytest.approx(8884.88, abs=0.01)
    assert capex.pmt(0, 8, 12) == 0


def test_cash_purchase_goes_out_in_full_and_depreciates_straight_line(blank):
    blank.capex = Capex(items=[item()])
    model = run(blank)
    assert total(model, "capex_investing") == pytest.approx(-120_000)
    assert total(model, "debt_service") == 0
    # In service from March: ten months of 2,000 inside the 12-month horizon.
    assert sum(p["depreciation"] for p in model.pnl) == pytest.approx(20_000)
    assert model.extras["capex"]["totals"]["depreciation"] == pytest.approx(20_000)


def test_financed_purchase_pays_down_payment_then_amortises(blank):
    blank.capex = Capex(items=[item(date=D(2026, 2, 10), funding="loan", down_payment_pct=25, term_months=12, annual_rate_pct=6)])
    model = run(blank)
    payment = capex.pmt(90_000, 6, 12)
    assert total(model, "capex_investing") == pytest.approx(-30_000)
    # Bought in month 1 (Feb): payments start in month 2 and 10 fall inside the horizon.
    assert total(model, "debt_service") == pytest.approx(-10 * payment)
    row = model.extras["capex"]["items"][0]
    assert row["financed"] == pytest.approx(90_000) and row["monthly_payment"] == pytest.approx(payment)
    assert sum(p["interest"] for p in model.pnl) > 0


def test_items_outside_the_horizon_do_nothing(blank):
    blank.capex = Capex(items=[item(date=D(2025, 6, 1)), item(date=D(2027, 6, 1))])
    model = run(blank)
    assert total(model, "capex_investing") == 0
    assert all(not i["in_horizon"] for i in model.extras["capex"]["items"])


def test_maintenance_capex_is_a_share_of_revenue(blank):
    blank.sales.monthly_revenue = 100_000
    blank.capex = Capex(maintenance_pct_revenue=2)
    model = run(blank)
    assert total(model, "capex_investing") == pytest.approx(-2_000 * 12)
    assert model.extras["capex"]["totals"]["maintenance"] == pytest.approx(24_000)


def test_growth_capex_flexes_with_scenario_but_maintenance_does_not(blank):
    blank.capex = Capex(
        growth_revenue_link=0.5,
        items=[item(name="Growth", amount=100_000), item(name="Keep-the-lights-on", amount=50_000, kind="maintenance", date=D(2026, 4, 1))],
    )
    base = run(blank)
    assert total(base, "capex_investing") == pytest.approx(-150_000)
    down = run(blank, Adjustments(revenue_change_pct=-20, capex_change_pct=-10))
    # growth x (1 + 0.5 * -20% + -10%) = x0.8; maintenance unchanged
    assert total(down, "capex_investing") == pytest.approx(-(80_000 + 50_000))
    assert down.extras["capex"]["totals"]["growth_scale"] == pytest.approx(0.8)


def test_depreciation_cuts_tax_but_not_cash_before_tax(blank):
    blank.general.tax_rate_pct = 25
    blank.sales.monthly_revenue = 100_000
    plain = run(blank)
    blank.capex = Capex(existing_depreciation_monthly=10_000)
    shielded = run(blank)
    # Three quarterly payments land inside the 12 months; each saves 25% x 30,000.
    assert total(plain, "taxes") - total(shielded, "taxes") == pytest.approx(-22_500)
    assert total(plain, "capex_investing") == total(shielded, "capex_investing") == 0


# --------------------------------------------------------------------------- #
# Macro data
# --------------------------------------------------------------------------- #


def fred_csv(series_id, values, start=D(2022, 1, 31), step_days=30):
    lines = [f"observation_date,{series_id}"]
    for i, v in enumerate(values):
        lines.append(f"{start + dt.timedelta(days=step_days * i)},{v}")
    return "\n".join(lines) + "\n"


def test_csv_parser_skips_missing_markers():
    text = "observation_date,X\n2025-01-01,1.5\n2025-01-02,.\n2025-01-03,\n2025-01-04,2.5\n"
    assert macro.parse_csv(text) == [(D(2025, 1, 1), 1.5), (D(2025, 1, 4), 2.5)]


def test_level_series_reports_latest_and_twelve_month_change():
    values = [4.0] * 24 + [5.5] * 12
    s = macro.build_series("fed_funds", fred_csv("FEDFUNDS", values))
    assert s["latest"] == 5.5
    assert s["year_ago"] == 4.0 and s["change_12m"] == pytest.approx(1.5)


def test_yoy_series_turns_an_index_into_percent_growth():
    index = [100 * 1.003 ** i for i in range(40)]  # 0.3% per month
    s = macro.build_series("cpi", fred_csv("CPIAUCSL", index))
    assert s["latest"] == pytest.approx((1.003 ** 12 - 1) * 100, abs=0.01)


@pytest.fixture
def fake_fred(monkeypatch):
    macro.reset_cache()
    calls = {"n": 0, "fail": False}

    def fetch(series_id):
        calls["n"] += 1
        if calls["fail"]:
            raise OSError("no network")
        if series_id in ("CPIAUCSL", "GDPC1"):
            return fred_csv(series_id, [100 * 1.04 ** (i / 12 if series_id == "CPIAUCSL" else i / 4) for i in range(40)],
                            step_days=30 if series_id == "CPIAUCSL" else 91)
        return fred_csv(series_id, [3.0] * 30 + [4.0] * 8)

    monkeypatch.setattr(macro, "_fetch_csv", fetch)
    yield calls
    macro.reset_cache()


def test_macro_is_cached_between_calls(fake_fred):
    first = macro.get_macro()
    n = fake_fred["n"]
    assert first["status"] == "live" and len(first["series"]) == len(macro.SERIES)
    macro.get_macro()
    assert fake_fred["n"] == n  # served from cache


def test_macro_suggestions_are_relative_to_the_two_percent_norm(fake_fred):
    sug = macro.get_macro()["suggestions"]
    assert sug["rate_change_pts"]["value"] == pytest.approx(1.0)
    assert sug["cost_inflation_pct"]["value"] == pytest.approx(4.0 - 2.0, abs=0.1)
    assert sug["demand_growth_pct"]["value"] == pytest.approx(4.0 - 2.0, abs=0.1)


def test_macro_falls_back_to_stale_data_then_to_unavailable(fake_fred):
    macro.get_macro()
    fake_fred["fail"] = True
    stale = macro.get_macro(force=True)
    assert stale["status"] == "stale" and stale["series"]
    macro.reset_cache()
    gone = macro.get_macro(force=True)
    assert gone["status"] == "unavailable" and gone["series"] == [] and gone["suggestions"] == {}


# --------------------------------------------------------------------------- #
# Macro overlay
# --------------------------------------------------------------------------- #


def test_overlay_does_nothing_unless_applied(blank):
    blank.sales.monthly_revenue = 100_000
    blank.macro = Macro(apply=False, demand_growth_pct=20, cost_inflation_pct=10, rate_change_pts=2)
    off = run(blank)
    plain_cfg = blank.model_copy(deep=True)
    plain_cfg.macro = Macro()
    assert [p["revenue"] for p in off.pnl] == [p["revenue"] for p in run(plain_cfg).pnl]


def test_demand_growth_compounds_into_revenue(blank):
    blank.sales.monthly_revenue = 100_000
    blank.macro = Macro(apply=True, demand_growth_pct=12)
    pnl = run(blank).pnl
    assert pnl[0]["revenue"] == pytest.approx(100_000)
    assert pnl[11]["revenue"] == pytest.approx(100_000 * (1.12 ** (1 / 12)) ** 11)


def test_inflation_lifts_fixed_opex_and_salaries_but_not_pct_of_revenue_lines(blank):
    blank.sales.monthly_revenue = 100_000
    blank.opex = [OpexLine(name="Rent", kind="fixed", amount=10_000), OpexLine(name="Marketing", kind="pct_revenue", amount=5)]
    blank.payroll = Payroll(headcount=1, avg_salary=120_000, burden_pct=0, salary_growth_pct_annual=0)
    blank.macro = Macro(apply=True, cost_inflation_pct=12)
    pnl = run(blank).pnl
    month6 = 1.12 ** (6 / 12)
    assert pnl[6]["opex"] == pytest.approx(10_000 * month6 + 5_000)
    assert pnl[6]["payroll"] == pytest.approx(10_000 * month6)


def test_rate_overlay_moves_only_floating_debt_and_new_financing(blank):
    blank.loans = [
        Loan(name="Floating", balance=100_000, annual_rate_pct=6, monthly_payment=2_000, floating=True),
        Loan(name="Fixed", balance=100_000, annual_rate_pct=6, monthly_payment=2_000, floating=False),
    ]
    before = sum(p["interest"] for p in run(blank).pnl)
    blank.macro = Macro(apply=True, rate_change_pts=2)
    after = sum(p["interest"] for p in run(blank).pnl)
    assert after > before
    blank.loans[0].floating = False
    assert sum(p["interest"] for p in run(blank).pnl) == pytest.approx(before)

    blank.capex = Capex(items=[item(date=D(2026, 2, 10), funding="loan", down_payment_pct=0, term_months=12, annual_rate_pct=6)])
    plain = blank.model_copy(deep=True)
    plain.macro = Macro()
    assert total(run(blank), "debt_service") < total(run(plain), "debt_service")  # bigger payments, more negative


def test_forecast_reports_the_cash_impact_of_the_overlay(blank):
    blank.sales.monthly_revenue = 100_000
    req = ForecastRequest(assumptions=blank)
    assert engine.forecast([], req)["macro"]["ending_cash_impact"] == 0
    blank.macro = Macro(apply=True, demand_growth_pct=10)
    out = engine.forecast([], ForecastRequest(assumptions=blank))
    assert out["macro"]["applied"] and out["macro"]["ending_cash_impact"] > 0


# --------------------------------------------------------------------------- #
# Micro trends
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def trend_data():
    invoices = ar.parse_invoices(ar.load_invoice_rows())
    bills = ap.parse_bills(ap.load_bill_rows())
    return trends.build_trends(invoices, bills, ar.snapshot_date(invoices))


def test_partial_months_are_flagged_and_excluded_from_signals(trend_data):
    months = trend_data["months"]
    assert months[0]["partial_reason"] == "start" and months[-1]["partial_reason"] == "end"
    assert all(not m["partial"] for m in months[1:-1])
    assert any("partial month" in c for c in trend_data["caveats"])
    revenue = next(s for s in trend_data["signals"] if s["key"] == "revenue")
    complete = [m for m in months if not m["partial"]]
    w = revenue["window_months"]
    assert revenue["current"] == pytest.approx(sum(m["invoiced"] for m in complete[-w:]))
    assert revenue["previous"] == pytest.approx(sum(m["invoiced"] for m in complete[-2 * w : -w]))


def test_signal_tone_depends_on_direction_and_whether_higher_is_good(trend_data):
    for s in trend_data["signals"]:
        if s["key"] == "days_to_pay" and s["change"] > 0.5:
            assert s["tone"] == "bad"
        if s["key"] == "revenue" and s["change"] > 1:
            assert s["tone"] == "good"


def test_short_history_has_no_seasonality(trend_data):
    assert trend_data["seasonality"] is None and "at least 12" in trend_data["seasonality_note"]


def test_implied_growth_recovers_a_known_growth_rate():
    invoices = []
    for k in range(8):
        month = 1 + k
        invoices.append(
            ar.Invoice(str(k), "C1", D(2025, month, 1), D(2025, month, 28), 100_000 * 1.05 ** k, None, 100_000 * 1.05 ** k, 30)
        )
    result = trends.build_trends(invoices, [], D(2025, 8, 31))
    assert result["implied"]["growth"]["monthly_growth_pct"] == pytest.approx(5.0, abs=0.01)


# --------------------------------------------------------------------------- #
# HTTP API
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_api_forecast_accepts_a_pre_upgrade_assumptions_payload(client):
    """Assumptions saved in a browser before AP/capex/macro existed must still run."""
    body = client.get("/cashflow/defaults").json()
    legacy = {k: v for k, v in body["assumptions"].items() if k not in ("ap", "capex", "macro")}
    r = client.post("/cashflow/forecast", json={"assumptions": legacy})
    assert r.status_code == 200
    out = r.json()
    assert out["capex"]["totals"]["cash_capex"] == 0 and out["macro"]["applied"] is False
    assert out["ap"]["open_total"] >= 0


def test_api_defaults_wire_in_bills_and_a_capex_plan(client):
    body = client.get("/cashflow/defaults").json()
    a = body["assumptions"]
    assert body["data_summary"]["ap"]["bill_count"] > 0
    assert a["ap"]["use_open_bills"] is True
    assert len(a["capex"]["items"]) >= 1 and a["one_time"] == []
    out = client.post("/cashflow/forecast", json={"assumptions": a}).json()
    assert out["ap"]["using_bills"] is True and out["ap"]["open_total"] == pytest.approx(body["data_summary"]["ap"]["open_ap"], abs=1)
    assert out["capex"]["totals"]["depreciation"] > 0
    assert len(out["capex"]["monthly"]) == 12


def test_api_scenarios_include_capex_in_the_comparison_run(client):
    a = client.get("/cashflow/defaults").json()["assumptions"]
    worst = client.post("/cashflow/forecast", json={"assumptions": a, "scenario": "worst"}).json()
    base = client.post("/cashflow/forecast", json={"assumptions": a, "scenario": "base"}).json()
    assert worst["capex"]["totals"]["growth_scale"] < base["capex"]["totals"]["growth_scale"]


def test_api_trends_endpoint(client):
    out = client.get("/cashflow/trends").json()
    assert out["months"] and out["signals"] and out["as_of"] == "2026-04-09"


def test_api_macro_endpoint_uses_the_cache_and_reports_status(client, fake_fred):
    out = client.get("/cashflow/macro").json()
    assert out["status"] == "live" and out["series"][0]["history"]
    fake_fred["fail"] = True
    assert client.get("/cashflow/macro?refresh=true").json()["status"] == "stale"
