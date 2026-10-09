"""The ML framework: leak-free datasets, honest validation, registry, and shadow-mode guarantees."""
import copy
import datetime as dt

import numpy as np
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cashflow import ap, ar, engine, gl
from cashflow.models import ForecastRequest
from cashflow.router import router
from mlfw import core, service, tasks
from mlfw.core import BaselineSpec, Dataset, ModelSpec, Registry, Row

INV = ar.parse_invoices(ar.load_invoice_rows())
D = dt.date


@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    s = service.Service(Registry(str(tmp_path_factory.mktemp("store"))))
    s.overview()
    return s


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("MODEL_STORE_DIR", str(tmp_path))
    monkeypatch.setattr(service, "_service", None)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---- datasets are point-in-time ------------------------------------------

def test_features_ignore_everything_after_the_prediction_date():
    cls, _ = tasks.build_invoice_datasets(INV)
    row = cls.rows[len(cls.rows) // 2]
    bumped = copy.deepcopy(INV)
    for i in bumped:  # rewrite the future: payments and invoices after the row's date
        if i.payment_date and i.payment_date > row.time:
            i.payment_date = i.payment_date + dt.timedelta(days=90)
    cls2, _ = tasks.build_invoice_datasets(bumped)
    again = next(r for r in cls2.rows if r.id == row.id)
    assert again.features == row.features


def test_rows_become_known_after_they_are_predicted():
    cls, reg = tasks.build_invoice_datasets(INV)
    for ds in (cls, reg):
        assert all(r.known_at >= r.time for r in ds.rows)


def test_labels_follow_the_definition():
    cls, reg = tasks.build_invoice_datasets(INV)
    by_id = {i.invoice_id: i for i in INV}
    for r in cls.rows[::40]:
        i = by_id[r.id]
        expect = ((i.payment_date - i.due_date).days > tasks.LATE_DAYS) if i.payment_date else True
        assert r.target == float(expect)
    assert len(reg.rows) == sum(1 for i in INV if i.payment_date)
    assert all(-15 <= r.target <= 120 for r in reg.rows)


# ---- walk-forward folds do not leak ----------------------------------------

def test_training_rows_are_always_known_before_the_test_block():
    cls, _ = tasks.build_invoice_datasets(INV)
    folds = core.make_folds(cls.rows, 30, 80)
    assert folds.folds
    for f, train, test in zip(folds.folds, folds.train_sets, folds.test_sets):
        assert all(r.known_at < f["test_start"] for r in train)
        assert all(f["test_start"] <= r.time < f["test_end"] for r in test)
        assert not ({r.id for r in train} & {r.id for r in test})


# ---- the framework neither invents nor hides skill ---------------------------------

def synthetic(signal: float, n=600, seed=3):
    rng = np.random.default_rng(seed)
    rows = []
    for i in range(n):
        x = rng.normal()
        y = float(rng.random() < 1 / (1 + np.exp(-signal * x)))
        t = D(2026, 1, 1) + dt.timedelta(days=i // 3)
        rows.append(Row(str(i), f"g{i % 30}", t, t + dt.timedelta(days=5), {"x": x, "noise": rng.normal()}, y))
    return Dataset("syn", "classification", rows, ["x", "noise"])


def run_syn(ds):
    models = [ModelSpec("logistic", tasks.logistic, ["x", "noise"])]
    bases = [BaselineSpec("noise rule", lambda tr, r: r.features["noise"], primary=True)]
    ev = core.evaluate(ds, models, bases, block_days=30, min_train=50, reps=150)
    return ev, core.paired_difference(ds, ev, "logistic", "noise rule", reps=150)


def test_finds_real_signal():
    ev, diff = run_syn(synthetic(2.5))
    assert ev["point"]["logistic"]["auc"] > 0.8
    assert core.verdict(diff, True) == "beats"


def test_does_not_find_signal_in_pure_noise():
    ev, diff = run_syn(synthetic(0.0))
    lo, hi = ev["ci"]["logistic"]["auc"]
    assert lo <= 0.5 <= hi
    assert core.verdict(diff, True) in ("ties", "unclear")


def test_verdict_logic():
    d = {"ci_low": 0.01, "ci_high": 0.05, "difference": 0.03}
    assert core.verdict(d, True) == "beats" and core.verdict(d, False) == "worse"
    assert core.verdict({"ci_low": -0.02, "ci_high": 0.03, "difference": 0.0}, True) == "ties"
    assert core.verdict({"ci_low": None, "ci_high": None, "difference": 0.0}, True) == "unclear"


def test_psi_flags_shift_and_not_stability():
    rng = np.random.default_rng(1)
    a = rng.normal(0, 1, 5000)
    assert core.psi(a, rng.normal(0, 1, 2000)) < 0.1
    assert core.psi(a, rng.normal(2, 1, 2000)) > 0.25
    assert core.psi(a[:5], a) is None


def test_metrics():
    y = np.array([0, 0, 1, 1])
    assert core.auc(y, np.array([0.1, 0.2, 0.8, 0.9])) == 1.0
    assert core.auc(y, np.array([0.9, 0.8, 0.2, 0.1])) == 0.0
    assert core.auc(np.ones(4), np.arange(4)) is None
    assert core.mae(np.array([1.0, 3.0]), np.array([2.0, 5.0])) == 1.5


# ---- registry ------------------------------------------------------------------

def test_registry_versions_persist_and_reload(tmp_path):
    reg = Registry(str(tmp_path))
    a = reg.save({"task": "t", "model": "m", "rows": 3, "data_fingerprint": "abc"}, estimator={"x": 1})
    b = reg.save({"task": "t", "model": "m", "rows": 4, "data_fingerprint": "def"})
    assert (a["version"], b["version"]) == (1, 2) and a["id"] == "t.m.v1"
    assert [r["id"] for r in reg.latest()] == ["t.m.v2"] and len(reg.history("t", "m")) == 2
    assert (tmp_path / "t.m.v1.joblib").exists()
    again = Registry(str(tmp_path))
    assert [r["id"] for r in again.records] == ["t.m.v1", "t.m.v2"] and again.next_version("t", "m") == 3


# ---- the service on the sample data -------------------------------------------------

def test_overview_covers_every_task(svc):
    o = svc.overview()
    names = [t["task"] for t in o["tasks"]]
    assert names == ["invoice_late", "invoice_days_late", "learned_credit_score", "bill_days_late", "spend_revenue_drivers"]
    assert all(t["status"] == "ok" for t in o["tasks"]) and o["mode"] == "shadow"
    assert o["summary"]["tested"] == 5 and o["data"]["caveat"]
    for t in o["tasks"]:
        assert t["findings"] and t["comparison"]["verdict"] in ("beats", "ties", "worse", "unclear")
        assert any(b.get("primary") for b in t["baselines"])


def test_every_model_is_in_the_registry_with_its_data(svc):
    ids = {r["id"] for r in svc.overview()["registry"]}
    assert {"invoice_late.logistic.v1", "invoice_late.gbm.v1", "bill_days_late.gbm.v1", "learned_credit_score.learned_weights.v1"} <= ids
    rec = next(r for r in svc.registry.records if r["id"] == "invoice_late.gbm.v1")
    assert rec["data_fingerprint"] and rec["features"] and rec["validation_metrics"]["auc"] > 0.5


def test_results_are_reproducible(tmp_path):
    a = service.Service(Registry(str(tmp_path / "a"))).overview()
    b = service.Service(Registry(str(tmp_path / "b"))).overview()
    for ta, tb in zip(a["tasks"], b["tasks"]):
        assert ta["comparison"]["difference"] == tb["comparison"]["difference"]
        assert [m["metrics"] for m in ta["models"]] == [m["metrics"] for m in tb["models"]]


def test_cache_and_retrain_versions(tmp_path):
    s = service.Service(Registry(str(tmp_path)))
    first = s.overview()
    assert s.overview() is first  # unchanged data: served from cache, no new versions
    again = s.overview(force=True)
    assert any(r["id"] == "invoice_late.gbm.v2" for r in again["registry"])


def test_learned_weights_are_a_distribution(svc):
    lw = next(t for t in svc.overview()["tasks"] if t["task"] == "learned_credit_score")["learned_weights"]
    assert len(lw) == 5 and abs(sum(w["learned_weight"] for w in lw) - 1) < 1e-9 or sum(w["learned_weight"] for w in lw) == 0
    assert abs(sum(w["current_weight"] for w in lw) - 1) < 1e-9


def test_open_invoice_predictions_cover_only_not_yet_due(svc):
    p = svc.open_invoice_predictions(limit=100)
    assert p["available"] and p["invoices"]
    assert all(0 <= r["probability_late"] <= 1 for r in p["invoices"])
    assert all(r["due_date"] > str(p["as_of"]) for r in p["invoices"])
    assert p["summary"]["expected_late_amount"] <= p["summary"]["amount"]


def test_the_cash_forecast_is_untouched_by_the_models(tmp_path):
    rows = ar.load_invoice_rows()
    a = engine.default_assumptions(rows, bill_rows=ap.load_bill_rows(), payroll_rows=gl.load_payroll_rows(), gl_data=gl.load_gl())["assumptions"]
    req = ForecastRequest(assumptions=a)
    before = engine.forecast(rows, req, ap.load_bill_rows(), gl.load_gl())
    service.Service(Registry(str(tmp_path))).overview()
    after = engine.forecast(rows, req, ap.load_bill_rows(), gl.load_gl())
    assert before["kpis"]["monthly"] == after["kpis"]["monthly"] and before["monthly"] == after["monthly"]


# ---- API -------------------------------------------------------------------------

def test_endpoints(client):
    o = client.get("/cashflow/ml/overview").json()
    assert o["mode"] == "shadow" and len(o["tasks"]) == 5
    r = client.post("/cashflow/ml/retrain").json()
    assert any(x["id"].endswith(".v2") for x in r["registry"])
    p = client.get("/cashflow/ml/predictions/open-invoices?limit=5").json()
    assert p["available"] and len(p["invoices"]) == 5
    assert client.get("/cashflow/ml/predictions/open-invoices?limit=0").status_code == 422
