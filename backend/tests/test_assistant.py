"""Tests for the receivables assistant (the model call is faked)."""
import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cashflow import ap, ar, assistant, engine, gl
from cashflow.models import Adjustments, ForecastRequest
from cashflow.router import router

ROWS = ar.load_invoice_rows()


def forecast_request(**adj):
    a = engine.default_assumptions(ROWS, bill_rows=ap.load_bill_rows(), payroll_rows=gl.load_payroll_rows(), gl_data=gl.load_gl())["assumptions"]
    return ForecastRequest(assumptions=a, adjustments=Adjustments(**adj))


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture
def fake(monkeypatch):
    calls = []

    def install(reply):
        def complete(prompt):
            calls.append(prompt)
            if isinstance(reply, Exception):
                raise reply
            return reply if isinstance(reply, str) else json.dumps(reply)

        monkeypatch.setattr(assistant, "complete", complete)
        return calls

    return install


def payload(message="Who should collections call first?", **kw):
    body = {"message": message, "forecast": forecast_request(**kw.pop("adj", {})).model_dump(mode="json")}
    body.update(kw)
    return body


def test_context_matches_the_forecast_numbers():
    req = forecast_request(collectability_change_pts=-10)
    result = engine.forecast(ROWS, req, ap.load_bill_rows(), gl.load_gl())
    ctx = assistant.build_context(result, ar.parse_invoices(ROWS))
    assert ctx["receivables"]["open_total"] == result["ar"]["open_total"]
    assert ctx["active_what_ifs"] == {"collectability_change_pts": -10}
    assert len(ctx["customer_cash_by_month"]) == 12
    assert len(ctx["top_customers"]) == 10
    assert ctx["impact_of_receivables_what_ifs"]["active"]


def test_context_includes_selected_customer_invoices():
    result = engine.forecast(ROWS, forecast_request(), ap.load_bill_rows(), gl.load_gl())
    cid = result["ar"]["customers"][0]["customer_id"]
    ctx = assistant.build_context(result, ar.parse_invoices(ROWS), cid)
    assert ctx["selected_customer"]["customer"] == cid
    assert ctx["selected_customer"]["open_invoices"]


def test_answer_and_suggestions_round_trip(client, fake):
    calls = fake({"answer": "Call C1010 first.", "suggested_whatifs": {"top_customer_delay_days": 30}, "follow_ups": ["What if they never pay?"]})
    r = client.post("/cashflow/ar-assistant", json=payload())
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "Call C1010 first."
    assert body["suggested_whatifs"] == {"top_customer_delay_days": 30}
    assert body["follow_ups"] == ["What if they never pay?"]
    assert "Who should collections call first?" in calls[0] and "open_total" in calls[0]


def test_suggestions_are_restricted_and_clamped(fake):
    fake({"answer": "x", "suggested_whatifs": {"top_customer_delay_days": 9999, "collectability_change_pts": -15, "extra_hires": 3,
                                               "past_due_delay_days": "soon", "extra_bad_debt_pct": True, "nonsense": 1}})
    out = assistant.ask({}, "q", [])
    assert out["suggested_whatifs"] == {"collectability_change_pts": -15}


def test_at_most_three_suggestions(fake):
    fake({"answer": "x", "suggested_whatifs": {"collection_delay_days": 5, "past_due_delay_days": 5, "top_customer_delay_days": 5, "collectability_change_pts": -5}})
    assert len(assistant.ask({}, "q", [])["suggested_whatifs"]) == 3


def test_non_json_reply_is_shown_as_the_answer(fake):
    fake("Collections should start with the oldest balances.")
    out = assistant.ask({}, "q", [])
    assert out["answer"].startswith("Collections should start") and out["suggested_whatifs"] == {}


def test_json_wrapped_in_text_is_parsed(fake):
    fake('Here you go: {"answer": "Fine.", "suggested_whatifs": {}} thanks')
    assert assistant.ask({}, "q", [])["answer"] == "Fine."


def test_missing_key_gives_503(client, monkeypatch):
    monkeypatch.setattr(assistant, "complete", assistant._default_complete)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    r = client.post("/cashflow/ar-assistant", json=payload())
    assert r.status_code == 503 and "OPENAI_API_KEY" in r.json()["detail"]


def test_model_failure_gives_502(client, fake):
    fake(RuntimeError("rate limited"))
    r = client.post("/cashflow/ar-assistant", json=payload())
    assert r.status_code == 502 and "rate limited" in r.json()["detail"]


def test_history_is_trimmed_and_prompt_has_bounds(fake):
    calls = fake({"answer": "ok"})
    hist = [{"role": "user", "content": f"msg-{i:04d}"} for i in range(30)]
    assistant.ask({}, "q", hist)
    assert "msg-0029" in calls[0] and "msg-0022" in calls[0] and "msg-0021" not in calls[0]
    assert '"top_customer_delay_days"' in calls[0] and '"max": 120' in calls[0]


def test_validation_rejects_empty_message(client):
    assert client.post("/cashflow/ar-assistant", json=payload(message="")).status_code == 422
