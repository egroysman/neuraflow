"""Payment-behavior credit score and its back-test."""
import csv
import datetime as dt

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cashflow import ar, credit
from cashflow.router import router

ROWS = ar.load_invoice_rows()
INV = ar.parse_invoices(ROWS)
AS_OF = ar.snapshot_date(INV)
BEHAVIOR = {r["CustomerID"]: r["Behavior"] for r in ROWS}  # only used to check the score, never to build it


def inv(i, cust, issued, due, paid, amount=1000.0):
    return ar.Invoice(str(i), cust, issued, due, amount, paid, 0.0 if paid else amount, 30)


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_scores_are_bounded_and_sorted_riskiest_first():
    rows = credit.score_customers(INV, AS_OF)
    assert len(rows) == 25
    assert all(0 <= r["score"] <= 100 for r in rows)
    assert [r["score"] for r in rows] == sorted(r["score"] for r in rows)
    assert {r["band"] for r in rows} <= {"Low risk", "Watch", "High risk"}
    for r in rows:
        assert abs(sum(c["weight"] for c in r["components"]) - 1) < 1e-9
        assert r["reasons"]


def test_score_recovers_the_hidden_payer_type_in_the_sample():
    rows = credit.score_customers(INV, AS_OF)
    late = [r["score"] for r in rows if BEHAVIOR[r["customer_id"]] == "late"]
    good = [r["score"] for r in rows if BEHAVIOR[r["customer_id"]] == "good"]
    assert sum(late) / len(late) < sum(good) / len(good) - 15


def test_slow_payer_scores_below_prompt_payer():
    d = dt.date
    prompt = [inv(i, "A", d(2026, 1, 1) + dt.timedelta(days=20 * i), d(2026, 1, 31) + dt.timedelta(days=20 * i), d(2026, 1, 31) + dt.timedelta(days=20 * i)) for i in range(6)]
    slow = [inv(i, "B", d(2026, 1, 1) + dt.timedelta(days=20 * i), d(2026, 1, 31) + dt.timedelta(days=20 * i), d(2026, 1, 31) + dt.timedelta(days=20 * i + 40)) for i in range(6)]
    when = d(2026, 6, 30)
    a, b = credit.score_customer(prompt, when), credit.score_customer(slow, when)
    assert a["score"] > 70 > 40 > b["score"] and a["band"] == "Low risk" and b["band"] == "High risk"


def test_no_peeking_at_the_future():
    d = dt.date
    items = [inv(1, "A", d(2026, 1, 1), d(2026, 1, 31), d(2026, 1, 31)), inv(2, "A", d(2026, 2, 1), d(2026, 3, 3), d(2026, 6, 1)),
             inv(3, "A", d(2026, 2, 5), d(2026, 3, 7), d(2026, 3, 7))]
    before = credit.score_customer(items, d(2026, 3, 20))
    # a payment made after the scoring date, or an invoice issued after it, must not change the score
    later = items + [inv(9, "A", d(2026, 4, 1), d(2026, 5, 1), d(2026, 9, 1))]
    items[1].payment_date = d(2026, 12, 31)
    assert credit.score_customer(later, d(2026, 3, 20))["score"] == before["score"]


def test_thin_history_is_pulled_toward_average_and_flagged():
    d = dt.date
    one = [inv(1, "A", d(2026, 1, 1), d(2026, 1, 31), d(2026, 3, 15))]
    s = credit.score_customer(one, d(2026, 4, 1))
    assert s["confidence"] == "low" and any("leans toward average" in r for r in s["reasons"])
    assert 30 < s["score"] < 60


def test_open_past_due_invoices_lower_the_score():
    d = dt.date
    paid = [inv(i, "A", d(2026, 1, 1), d(2026, 1, 31), d(2026, 1, 31)) for i in range(5)]
    base = credit.score_customer(paid, d(2026, 3, 1))["score"]
    stuck = credit.score_customer(paid + [inv(9, "A", d(2026, 1, 5), d(2026, 2, 4), None)], d(2026, 3, 1))
    assert stuck["score"] < base and stuck["past_due_amount"] == 1000.0 and stuck["oldest_days_past_due"] == 25


# ---- back-test ----------------------------------------------------------

BT = credit.backtest(INV)


def test_backtest_is_available_and_consistent():
    assert BT["available"]
    s = BT["sample"]
    assert s["invoices"] > 500 and s["customers"] == 25
    assert abs(s["base_late_rate"] - s["late_invoices"] / s["invoices"]) < 1e-12
    assert sum(b["invoices"] for b in BT["bands"]) == s["invoices"]
    assert BT["auc"]["ci_low"] <= BT["auc"]["value"] <= BT["auc"]["ci_high"]
    assert 0.5 < BT["auc"]["value"] <= 1.0


def test_backtest_uses_only_information_available_at_each_cutoff():
    recs, meta = credit.build_records(INV)
    by = {}
    for i in INV:
        by.setdefault(i.customer_id, []).append(i)
    for r in recs[::97]:  # spot-check: rescoring from a truncated history gives the same score
        known = [i for i in by[r["customer_id"]] if i.invoice_date <= r["cutoff"]]
        for i in known:
            if i.payment_date and i.payment_date > r["cutoff"]:
                pass
        assert credit.score_customer(by[r["customer_id"]], r["cutoff"])["score"] == r["score"]
        assert credit.score_customer(known, r["cutoff"])["score"] == r["score"]
        assert r["due_date"] > r["cutoff"]


def test_outcomes_match_the_definition():
    recs, meta = credit.build_records(INV, horizon_days=90, late_days=10)
    pay = {i.invoice_id: i for i in INV}
    for r in recs[::53]:
        i = pay[r["invoice_id"]]
        expect = (i.payment_date - i.due_date).days > 10 if i.payment_date else True
        assert r["late"] == int(expect)
        assert i.payment_date is None or i.payment_date > r["cutoff"]  # outcome not already known


def test_stricter_late_definition_lowers_the_late_rate():
    assert credit.backtest(INV, late_days=30)["sample"]["base_late_rate"] < credit.backtest(INV, late_days=0)["sample"]["base_late_rate"]


def test_findings_and_ingredient_diagnostics_present():
    assert len(BT["components"]) == 5 and all(c["auc"] is not None for c in BT["components"])
    assert BT["findings"] and BT["baselines"]


def test_too_little_history_is_reported_not_faked():
    short = [inv(1, "A", dt.date(2026, 1, 1), dt.date(2026, 1, 31), dt.date(2026, 2, 5))]
    assert credit.backtest(short)["available"] is False


def test_backtest_is_deterministic():
    again = credit.backtest(INV)
    assert again["auc"] == BT["auc"]


# ---- API ----------------------------------------------------------------

def test_credit_endpoint(client):
    r = client.get("/cashflow/credit").json()
    assert r["summary"]["customers"] == 25 and len(r["customers"]) == 25
    assert sum(b["customers"] for b in r["summary"]["bands"]) == 25


def test_validation_endpoint_and_csv(client):
    v = client.get("/cashflow/credit/validation?horizon_days=60&late_days=5").json()
    assert v["available"] and v["params"]["horizon_days"] == 60 and "records" not in v and v["caveat"]
    c = client.get("/cashflow/credit/validation/export")
    rows = list(csv.DictReader(c.text.splitlines()))
    assert c.headers["content-type"].startswith("text/csv") and len(rows) > 500
    assert {"cutoff", "customer_id", "score", "late"} <= set(rows[0])
    assert client.get("/cashflow/credit/validation?horizon_days=5").status_code == 422


def test_forecast_receivables_carry_scores():
    from cashflow import engine, gl, ap
    from cashflow.models import ForecastRequest
    a = engine.default_assumptions(ROWS, bill_rows=ap.load_bill_rows(), payroll_rows=gl.load_payroll_rows(), gl_data=gl.load_gl())["assumptions"]
    res = engine.forecast(ROWS, ForecastRequest(assumptions=a), ap.load_bill_rows(), gl.load_gl())
    assert all(c["credit_score"] is not None and c["credit_band"] for c in res["ar"]["customers"])
