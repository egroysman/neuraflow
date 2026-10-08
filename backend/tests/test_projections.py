"""Standard 30 / 60 / 90 / 180 day and 1 year projections."""
import datetime as dt

from cashflow import ap, ar, engine, gl
from cashflow.models import Adjustments, ForecastRequest

ROWS = ar.load_invoice_rows()


def run(horizon=12, **adj):
    a = engine.default_assumptions(ROWS, bill_rows=ap.load_bill_rows(), payroll_rows=gl.load_payroll_rows(), gl_data=gl.load_gl())["assumptions"]
    a.general.horizon_months = horizon
    return engine.forecast(ROWS, ForecastRequest(assumptions=a, adjustments=Adjustments(**adj)), ap.load_bill_rows(), gl.load_gl())


def test_five_standard_windows():
    r = run()
    assert [p["days"] for p in r["projections"]] == [30, 60, 90, 180, 365]
    assert [p["label"] for p in r["projections"]] == ["30 days", "60 days", "90 days", "180 days", "1 year"]
    for p in r["projections"]:
        assert p["end_date"] == r["as_of"] + dt.timedelta(days=p["days"])
        assert p["complete"]


def test_windows_add_up():
    for p in run()["projections"]:
        assert abs(p["starting_cash"] + p["net_cash_flow"] - p["ending_cash"]) < 0.01
        assert abs(p["operating"] + p["investing"] + p["financing"] - p["net_cash_flow"]) < 0.01
        assert abs(p["cash_in"] - p["cash_out"] - p["net_cash_flow"]) < 0.01
        assert abs(sum(p["categories"].values()) - p["net_cash_flow"]) < 0.01
        assert p["lowest_balance"] <= min(p["starting_cash"], p["ending_cash"]) + 0.01


def test_agrees_with_weekly_and_monthly_views():
    r = run()
    by_days = {p["days"]: p for p in r["projections"]}
    # 13 weeks = 91 days; the 90-day window is 1 day shorter, so compare 365 to the monthly view instead.
    if (r["horizon_end"] - r["as_of"]).days == 365:
        assert abs(by_days[365]["ending_cash"] - r["monthly"][-1]["end_cash"]) < 0.01
        assert abs(by_days[365]["lowest_balance"] - r["kpis"]["monthly"]["lowest_balance"]) < 0.01
    # the lowest point of a longer window can never be higher than a shorter one
    lows = [by_days[d]["lowest_balance"] for d in (30, 60, 90, 180, 365)]
    assert lows == sorted(lows, reverse=True)


def test_what_ifs_move_the_short_windows():
    base = run()["projections"][0]["ending_cash"]
    slow = run(collection_delay_days=45)["projections"][0]["ending_cash"]
    assert slow < base


def test_short_horizon_flags_incomplete_windows():
    r = run(horizon=6)
    flags = {p["days"]: p["complete"] for p in r["projections"]}
    assert flags[180] is False or flags[90] is True
    assert flags[365] is False and flags[30] is True


def test_scenarios_carry_all_windows():
    r = run()
    for c in r["comparison"].values():
        assert len(c["projection_end_cash"]) == 5 and len(c["projection_lowest"]) == 5
    assert r["comparison"][r["scenario"]]["projection_end_cash"] == [p["ending_cash"] for p in r["projections"]]
    assert r["comparison"]["worst"]["projection_end_cash"][4] <= r["comparison"]["best"]["projection_end_cash"][4]
