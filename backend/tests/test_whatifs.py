"""Tests for the tab-specific what-if adjustments."""
import datetime as dt

import pytest

from cashflow import ap, ar, engine, gl
from cashflow.models import Adjustments, ForecastRequest, Macro

ROWS = ar.load_invoice_rows()
BILLS = ap.load_bill_rows()


def base_assumptions():
    return engine.default_assumptions(ROWS, bill_rows=BILLS, payroll_rows=gl.load_payroll_rows(), gl_data=gl.load_gl())["assumptions"]


def run(adj=None, a=None, scenario="base"):
    return engine.forecast(ROWS, ForecastRequest(assumptions=a or base_assumptions(), scenario=scenario, adjustments=adj or Adjustments()), BILLS, gl.load_gl())


def end(r):
    return r["kpis"]["monthly"]["ending_cash"]


BASE = run()


@pytest.mark.parametrize(
    "adj,direction",
    [
        (Adjustments(collectability_change_pts=-20), -1),
        (Adjustments(past_due_delay_days=60), 0),  # timing only: ending cash may not move, lowest balance can
        (Adjustments(top_customer_delay_days=60), 0),
        (Adjustments(raise_change_pct_pts=8), -1),
        (Adjustments(extra_hires=5), -1),
        (Adjustments(bonus_change_pct=100), -1),
        (Adjustments(salary_change_pct=10), -1),
        (Adjustments(tax_rate_change_pts=10), -1),
        (Adjustments(rate_change_pts=3), -1),
        (Adjustments(capex_delay_months=12), 1),
    ],
)
def test_each_adjustment_moves_cash_the_right_way(adj, direction):
    r = run(adj)
    delta = end(r) - end(BASE)
    low = r["kpis"]["monthly"]["lowest_balance"] - BASE["kpis"]["monthly"]["lowest_balance"]
    if direction < 0:
        assert delta < 0
    elif direction > 0:
        assert delta > 0
    else:
        assert delta != 0 or low != 0


def test_balance_sheet_still_balances_with_every_new_adjustment():
    adj = Adjustments(collectability_change_pts=-15, past_due_delay_days=30, top_customer_delay_days=45, raise_change_pct_pts=4,
                      extra_hires=3, bonus_change_pct=50, salary_change_pct=5, capex_delay_months=6, rate_change_pts=2, tax_rate_change_pts=5)
    for scenario in ("base", "worst"):
        assert run(adj, scenario=scenario)["balance_sheet"]["max_abs_check"] < 0.01


def test_top_customer_delay_only_moves_that_customer():
    invoices = ar.parse_invoices(ROWS)
    as_of = ar.snapshot_date(invoices)
    from cashflow.models import Collections
    plain = ar.project_open_invoices(invoices, as_of, Collections())
    late = ar.project_open_invoices(invoices, as_of, Collections(), top_customer_delay_days=40)
    moved = {p["customer_id"] for p, q in zip(plain, late) if p["expected_date"] != q["expected_date"]}
    assert len(moved) == 1
    owed = {}
    for p in plain:
        owed[p["customer_id"]] = owed.get(p["customer_id"], 0) + p["open_amount"]
    assert moved == {max(owed, key=owed.get)}


def test_past_due_delay_leaves_current_invoices_alone():
    invoices = ar.parse_invoices(ROWS)
    as_of = ar.snapshot_date(invoices)
    from cashflow.models import Collections
    plain = ar.project_open_invoices(invoices, as_of, Collections())
    late = ar.project_open_invoices(invoices, as_of, Collections(), past_due_delay_days=30)
    for p, q in zip(plain, late):
        if p["days_past_due"] <= 0:
            assert p["expected_date"] == q["expected_date"]
        else:
            assert (q["expected_date"] - p["expected_date"]).days == 30


def test_collectability_is_clamped():
    invoices = ar.parse_invoices(ROWS)
    from cashflow.models import Collections
    out = ar.project_open_invoices(invoices, ar.snapshot_date(invoices), Collections(), collectability_change_pts=-50)
    assert all(0 <= p["probability"] <= 1 for p in out)


def test_extra_hires_show_up_in_payroll_summary():
    r = run(Adjustments(extra_hires=4))
    assert "What-if hires" in r["payroll"]["by_department"]
    assert r["payroll"]["headcount"][-1] == BASE["payroll"]["headcount"][-1] + 4


def test_capex_delay_moves_purchase_dates_for_growth_items_only():
    r = run(Adjustments(capex_delay_months=3))
    for it in r["capex"]["items"]:
        planned = it["planned_date"]
        if it["kind"] == "growth":
            assert it["date"] > planned
        else:
            assert it["date"] == planned


def test_whatif_impact_groups_report_only_active_groups():
    r = run(Adjustments(extra_hires=3, collectability_change_pts=-10))
    imp = r["whatif_impact"]
    assert set(imp) == set(Adjustments.GROUPS)
    assert imp["payroll"]["active"] and imp["ar"]["active"]
    assert not imp["capex"]["active"] and imp["capex"]["ending_cash_impact"] == 0
    assert imp["payroll"]["ending_cash_impact"] < 0 and imp["ar"]["ending_cash_impact"] < 0


def test_impacts_of_separate_groups_roughly_add_up_for_independent_groups():
    adj = Adjustments(extra_hires=3, capex_delay_months=3)
    r = run(adj)
    total = end(r) - end(BASE)
    parts = sum(v["ending_cash_impact"] for v in r["whatif_impact"].values())
    assert total == pytest.approx(parts, rel=0.05)


def test_presets_unchanged_by_new_fields():
    r = run(scenario="worst")
    assert r["effective_adjustments"]["extra_hires"] == 0 and r["effective_adjustments"]["rate_change_pts"] == 0


def test_rate_change_hits_floating_loans_only():
    a = base_assumptions()
    a.loans[0].floating = False
    fixed = run(Adjustments(rate_change_pts=4), a=a)
    assert fixed["pnl"][0]["interest"] == pytest.approx(run(a=a)["pnl"][0]["interest"])
    a.loans[0].floating = True
    assert run(Adjustments(rate_change_pts=4), a=a)["pnl"][0]["interest"] > run(a=a)["pnl"][0]["interest"]


def test_tax_rate_change_lowers_cash_only_when_profitable():
    r = run(Adjustments(tax_rate_change_pts=10))
    assert end(r) <= end(BASE)


def test_simple_payroll_mode_respects_new_levers():
    a = base_assumptions()
    a.payroll.use_roster = False
    base = run(a=a)["pnl"][3]["payroll"]
    assert run(Adjustments(extra_hires=2), a=a)["pnl"][3]["payroll"] > base
    assert run(Adjustments(salary_change_pct=10), a=a)["pnl"][3]["payroll"] == pytest.approx(base * 1.1, rel=0.001)


# ---------------------------- per-tab levers (round 2) ----------------------------

NEW_LEVERS = [
    ("bill_catchup_extra_days", 60, "payables"),
    ("top_vendor_delay_days", 60, "payables"),
    ("benefits_change_pct", 50, "payroll"),
    ("employer_tax_change_pts", 5, "payroll"),
    ("maintenance_capex_change_pct", 100, "capex"),
    ("down_payment_change_pts", 30, "capex"),
    ("extra_loan_payment", 5000, "financing"),
    ("equity_injection", 100000, "financing"),
    ("starting_cash_change", -50000, "ledger"),
    ("other_monthly_cash", -2000, "ledger"),
    ("one_time_cash_item", -30000, "ledger"),
    ("seasonal_swing_pct", 30, "trends"),
    ("top_customer_loss_pct", 50, "trends"),
    ("new_sales_dso_change_days", 30, "trends"),
]


@pytest.mark.parametrize("field,value,group", NEW_LEVERS)
def test_new_lever_changes_the_model_and_balance_sheet_still_balances(field, value, group):
    r = run(Adjustments(**{field: value}))
    assert r["whatif_impact"][group]["active"]
    timing = [w["categories"]["ap_open_bills"] for w in r["weekly"]] != [w["categories"]["ap_open_bills"] for w in BASE["weekly"]]
    changed = (
        timing
        or end(r) != end(BASE)
        or r["kpis"]["monthly"]["lowest_balance"] != BASE["kpis"]["monthly"]["lowest_balance"]
        or r["balance_sheet"]["months"][-1]["equity"] != BASE["balance_sheet"]["months"][-1]["equity"]
    )
    assert changed, field
    assert r["balance_sheet"]["max_abs_check"] < 0.01


def test_every_lever_belongs_to_exactly_one_group():
    seen = {}
    for g, fields in Adjustments.GROUPS.items():
        for f in fields:
            assert f not in seen, f
            seen[f] = g
    assert set(seen) == set(Adjustments.model_fields)


def test_equity_injection_and_loan_prepayment_move_debt_and_cash():
    r = run(Adjustments(equity_injection=100000))
    assert end(r) == pytest.approx(end(BASE) + 100000, abs=1)
    r2 = run(Adjustments(extra_loan_payment=5000))
    assert r2["balance_sheet"]["months"][-1]["debt"] < BASE["balance_sheet"]["months"][-1]["debt"]


def test_starting_cash_change_shifts_every_balance():
    r = run(Adjustments(starting_cash_change=25000))
    assert r["balance_sheet"]["opening"]["cash"] == BASE["balance_sheet"]["opening"]["cash"] + 25000
    assert end(r) == pytest.approx(end(BASE) + 25000, abs=1)


def test_top_vendor_delay_moves_only_that_vendor():
    bills = ap.parse_bills(BILLS)
    as_of = ar.snapshot_date(ar.parse_invoices(ROWS))
    plain = ap.project_open_bills(bills, as_of)
    late = ap.project_open_bills(bills, as_of, top_vendor_delay_days=30)
    by_id = {p["bill_id"]: p for p in plain}
    moved = {q["vendor_id"] for q in late if q["expected_date"] != by_id[q["bill_id"]]["expected_date"]}
    assert len(moved) == 1


def test_top_customer_loss_cuts_revenue_by_that_customers_share():
    r = run(Adjustments(top_customer_loss_pct=100))
    assert r["pnl"][0]["revenue"] < BASE["pnl"][0]["revenue"] * 0.97


def test_seasonal_swing_is_zero_sum_shaped_peak_in_december():
    r = run(Adjustments(seasonal_swing_pct=40))
    months = {p["label"][:3]: p["revenue"] / b["revenue"] for p, b in zip(r["pnl"], BASE["pnl"])}
    assert months["Dec"] > 1.1 and months["Jun"] < 0.9
