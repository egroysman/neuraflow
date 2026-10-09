"""Runs the ML tasks on the loaded structured data and reports how they score against today's methods."""
from __future__ import annotations

import datetime as dt
import math
import threading
from typing import Any, Dict, List, Optional, Sequence

import numpy as np

from cashflow import ap, ar, credit, gl

from . import core, tasks
from .core import Dataset, Registry

MODE = "shadow"
PRINCIPLES = [
    "Every feature uses only what was known on the date of the prediction.",
    "Models are tested by walking forward through time: trained on the past, scored on the future.",
    "Every model is compared with a simple rule. A model has to beat the rule to earn a role.",
    "Confidence ranges come from re-sampling whole customers and vendors, because their invoices are not independent.",
    "Nothing here changes the cash flow forecast. Models run in shadow mode until they win.",
]


def _clean(v: Any) -> Any:
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_clean(x) for x in v]
    if isinstance(v, (np.floating,)):
        return None if not np.isfinite(v) else float(v)
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, float):
        return None if not math.isfinite(v) else v
    if isinstance(v, (dt.date, dt.datetime)):
        return v.isoformat()
    return v


class MLData:
    def __init__(self, invoices: Sequence[ar.Invoice], bills: Sequence[ap.Bill], gl_data: Optional[Dict[str, Any]]):
        self.invoices = list(invoices)
        self.bills = list(bills)
        self.gl_data = gl_data
        self.as_of = ar.snapshot_date(self.invoices) if self.invoices else dt.date.today()
        paid = [i.payment_date for i in self.invoices if i.payment_date]
        self.data_end = max(paid) if paid else self.as_of

    @classmethod
    def load(cls) -> "MLData":
        return cls(ar.parse_invoices(ar.load_invoice_rows()), ap.parse_bills(ap.load_bill_rows()), gl.load_gl())

    def key(self) -> str:
        return f"{len(self.invoices)}|{round(sum(i.amount for i in self.invoices), 2)}|{len(self.bills)}|{self.data_end}|{bool(self.gl_data)}"

    def gl_months(self) -> List[Dict[str, Any]]:
        if not self.gl_data:
            return []
        months = gl.monthly_actuals(gl.prepare(self.gl_data), self.as_of)
        return [m for m in months if not m.get("partial")]


def _metrics_block(ev: Dict[str, Any], name: str) -> Dict[str, Any]:
    return {m: {"value": v, "ci": ev["ci"][name].get(m)} for m, v in ev["point"][name].items()}


def _verdict_text(metric: str, best: str, label: str, base: str, v: str, point: Dict[str, Any], diff: Dict[str, Any]) -> str:
    unit = "AUC" if metric == "auc" else "average miss, in days"
    a, b = point[best][metric], point[base][metric]
    rng = f" (95% range {diff['ci_low']:+.3f} to {diff['ci_high']:+.3f})" if diff["ci_low"] is not None else ""
    phrase = {"beats": "beats", "ties": "is statistically tied with", "worse": "does worse than", "unclear": "cannot be separated from"}[v]
    return f"{label} {phrase} the simple rule \"{base}\" on {unit}: {a:.3f} vs {b:.3f}{rng}."


class Service:
    def __init__(self, registry: Optional[Registry] = None):
        self.registry = registry or Registry()
        self._lock = threading.Lock()
        self._cache: Optional[Dict[str, Any]] = None
        self._cache_key: Optional[str] = None
        self.estimators: Dict[str, Any] = {}
        self.data: Optional[MLData] = None

    # -- one modelled task --------------------------------------------------
    def _run_task(self, name: str, ds: Dataset, data: MLData, min_train: int) -> Dict[str, Any]:
        spec = tasks.TASKS[name]
        report: Dict[str, Any] = {
            "task": name, "title": spec["title"], "description": spec["description"], "feeds": spec["feeds"],
            "kind": ds.kind, "mode": MODE, "notes": ds.notes,
            "data": {"rows": len(ds.rows), "groups": len({r.group for r in ds.rows}), "fingerprint": ds.fingerprint(),
                     "features": len(ds.feature_names),
                     "first": min((r.time for r in ds.rows), default=None), "last": max((r.time for r in ds.rows), default=None)},
        }
        if ds.kind == "classification" and ds.rows:
            report["data"]["positive_rate"] = float(np.mean([r.target for r in ds.rows]))
        ev = core.evaluate(ds, spec["models"], spec["baselines"], block_days=30, min_train=min_train)
        if ev["status"] != "ok":
            return report | {"status": "insufficient_data", "folds": [], "findings": ["Not enough history to test this model yet."], "models": [], "baselines": []}

        metric, higher = ev["primary_metric"], ev["higher_is_better"]
        model_names = [m.name for m in spec["models"]]
        labels = {m.name: m.label or m.name for m in spec["models"]}
        best = max(model_names, key=lambda n: ev["point"][n][metric] * (1 if higher else -1))
        primary = next(b.name for b in spec["baselines"] if b.primary)
        diff = core.paired_difference(ds, ev, best, primary)
        v = core.verdict(diff, higher)
        others = []
        for b in spec["baselines"]:
            if b.name != primary and (ds.kind == "regression" or b.is_probability is False or True):
                try:
                    d2 = core.paired_difference(ds, ev, best, b.name)
                    others.append({"baseline": b.name, **d2, "verdict": core.verdict(d2, higher)})
                except Exception:
                    pass

        # final models, fitted on every labelled row, go into the registry
        finals = []
        for m in spec["models"]:
            est = m.make()
            X, y = ds.matrix(ds.rows, m.features), ds.target(ds.rows)
            est.fit(X, y)
            self.estimators[f"{name}.{m.name}"] = (est, m.features)
            imp = core.importances(est, m.features)
            rec = self.registry.save(
                {"task": name, "model": m.name, "label": labels[m.name], "kind": ds.kind, "mode": MODE,
                 "data_fingerprint": report["data"]["fingerprint"], "rows": len(ds.rows),
                 "train_window": [str(report["data"]["first"]), str(report["data"]["last"])],
                 "features": list(m.features), "validation_metrics": {k: v_ for k, v_ in ev["point"][m.name].items()},
                 "vs_baseline": {"baseline": primary, "verdict": v if m.name == best else None},
                 "top_features": imp[:5]},
                est,
            )
            finals.append({"name": m.name, "importances": imp, "registry_id": rec["id"], "version": rec["version"]})

        def block(n: str, is_model: bool) -> Dict[str, Any]:
            out = {"name": n, "label": labels.get(n, n), "metrics": _metrics_block(ev, n), "is_model": is_model}
            if is_model:
                f = next(x for x in finals if x["name"] == n)
                out |= {"importances": f["importances"], "registry_id": f["registry_id"], "version": f["version"]}
            return out

        report |= {
            "status": "ok",
            "validation": {
                "method": "Walk-forward: each test block of 30 days is scored by a model trained only on rows whose outcome was already known before the block began.",
                "folds": ev["folds"], "test_rows": len(ev["test_rows"]), "primary_metric": metric, "higher_is_better": higher,
            },
            "models": [block(n, True) for n in model_names],
            "baselines": [block(b.name, False) | {"primary": b.primary} for b in spec["baselines"]],
            "comparison": {"best_model": best, "baseline": primary, "metric": metric, **diff, "verdict": v,
                           "also_vs": others, "text": _verdict_text(metric, best, labels[best], primary, v, ev["point"], diff)},
            "drift": core.drift_report(ds, [f for f in ds.feature_names if f not in ("trend_known", "due_month_sin", "due_month_cos")])[:8],
        }
        if ds.kind == "classification":
            idx = {r.id: i for i, r in enumerate(ev["test_rows"])}
            report["calibration"] = core.calibration_bins(ev["y"], ev["preds"][best])
        report["findings"] = [report["comparison"]["text"]] + self._more_findings(report, ds, best, labels)
        return report

    @staticmethod
    def _more_findings(report: Dict[str, Any], ds: Dataset, best: str, labels: Dict[str, str]) -> List[str]:
        out: List[str] = []
        top = next((m for m in report["models"] if m["name"] == best), None)
        if top and top.get("importances"):
            out.append("Most influential inputs: " + ", ".join(i["feature"].replace("_", " ") for i in top["importances"][:3]) + ".")
        if report["validation"]["test_rows"] < 200:
            out.append(f"Only {report['validation']['test_rows']} out-of-time predictions were scored, so treat this as an early read.")
        shifted = [d["feature"].replace("_", " ") for d in report.get("drift", []) if d["status"] == "shifted"]
        if shifted:
            out.append("Inputs that have shifted recently: " + ", ".join(shifted[:3]) + ".")
        return out

    # -- learned weights ------------------------------------------------------
    def _learned_weights(self, report: Dict[str, Any]) -> None:
        got = self.estimators.get("learned_credit_score.learned_weights")
        if not got:
            return
        est, feats = got
        coef = est.steps[-1][1].coef_.reshape(-1)  # positive = more likely late
        safe = [max(0.0, -c) for c in coef]  # an ingredient that predicts lateness must lower the score
        total = sum(safe) or 1.0
        rows = []
        for f, c, s in zip(feats, coef, safe):
            key = tasks.COMPONENT_KEYS[f]
            rows.append({"ingredient": credit.LABELS[key], "current_weight": credit.WEIGHTS[key], "learned_weight": s / total, "coefficient": float(c)})
        report["learned_weights"] = rows

    # -- statistical task: spend and revenue drivers -----------------------------
    def _run_drivers(self, data: MLData) -> Dict[str, Any]:
        months = data.gl_months()
        series = {k: [m[k] for m in months] for k in ("revenue", "cogs", "payroll", "opex")}
        report: Dict[str, Any] = {
            "task": "spend_revenue_drivers", "title": "Next month's revenue and costs",
            "description": "Predicts next month's revenue, cost of sales, payroll and operating expenses from the ledger's monthly history.",
            "feeds": "Forecast baselines", "kind": "regression", "mode": MODE,
            "data": {"rows": len(months), "groups": 4, "features": 1, "fingerprint": f"gl-{len(months)}", "first": months[0]["month"] if months else None, "last": months[-1]["month"] if months else None},
            "notes": [],
        }
        if len(months) < 4:
            return report | {"status": "insufficient_data", "models": [], "baselines": [], "findings": ["The ledger needs at least four complete months to test a forecast."], "folds": []}

        def trend(h: List[float]) -> float:
            t = np.arange(len(h))
            slope, icpt = np.polyfit(t, h, 1)
            return float(icpt + slope * len(h))

        def damped(h: List[float]) -> float:
            t = np.arange(len(h))
            slope = np.polyfit(t, h, 1)[0]
            return float(np.mean(h[-3:]) + 0.5 * slope * 2)

        methods = {
            "Linear trend": (trend, True), "Damped trend": (damped, True),
            "Trailing 3-month average (today)": (lambda h: float(np.mean(h[-3:])), False),
            "Last month": (lambda h: float(h[-1]), False),
        }
        errors: Dict[str, List[float]] = {k: [] for k in methods}
        pct: Dict[str, List[float]] = {k: [] for k in methods}
        origins = 0
        for name, vals in series.items():
            for o in range(3, len(vals)):
                hist, actual = vals[:o], vals[o]
                origins += 1
                for mname, (fn, _) in methods.items():
                    p = fn(hist)
                    errors[mname].append(abs(p - actual))
                    pct[mname].append(abs(p - actual) / abs(actual) if actual else 0.0)
        out_models, out_base = [], []
        for mname, (fn, is_model) in methods.items():
            blk = {"name": mname, "label": mname, "is_model": is_model,
                   "metrics": {"mape": {"value": float(np.mean(pct[mname])), "ci": None}, "mae": {"value": float(np.mean(errors[mname])), "ci": None}}}
            (out_models if is_model else out_base).append(blk | ({"primary": True} if mname.startswith("Trailing") else {}))
        best = min(out_models, key=lambda b: b["metrics"]["mape"]["value"])
        base = next(b for b in out_base if b.get("primary"))
        d = best["metrics"]["mape"]["value"] - base["metrics"]["mape"]["value"]
        report |= {
            "status": "ok",
            "validation": {"method": "Rolling origin: for each month, forecast the next one using only earlier months.", "folds": [], "test_rows": origins, "primary_metric": "mape", "higher_is_better": False},
            "models": out_models, "baselines": out_base,
            "comparison": {"best_model": best["name"], "baseline": base["name"], "metric": "mape", "difference": d, "ci_low": None, "ci_high": None, "verdict": "unclear",
                           "text": f"{best['name']} misses next month by {best['metrics']['mape']['value'] * 100:.1f}% on average versus {base['metrics']['mape']['value'] * 100:.1f}% for today's trailing average. With {len(months)} months of history this cannot be called either way."},
            "drift": [],
            "findings": [f"Only {len(months)} complete months are in the ledger ({origins} test forecasts), so no conclusion is possible. Twelve or more months are needed to see seasonality.", ],
        }
        report["findings"].insert(0, report["comparison"]["text"])
        simplest = min(out_base, key=lambda b: b["metrics"]["mape"]["value"])
        if simplest["metrics"]["mape"]["value"] < best["metrics"]["mape"]["value"]:
            report["findings"].insert(1, f"A simpler rule, \"{simplest['name']}\", did better still ({simplest['metrics']['mape']['value'] * 100:.1f}% average miss).")
        self.registry.save({"task": "spend_revenue_drivers", "model": best["name"].lower().replace(" ", "_"), "label": best["name"], "kind": "regression", "mode": MODE,
                            "data_fingerprint": report["data"]["fingerprint"], "rows": len(months), "train_window": [str(report["data"]["first"]), str(report["data"]["last"])],
                            "features": ["monthly history"], "validation_metrics": {"mape": best["metrics"]["mape"]["value"]}, "vs_baseline": {"baseline": base["name"], "verdict": None}, "top_features": []})
        return report

    # -- everything -----------------------------------------------------------
    def overview(self, force: bool = False) -> Dict[str, Any]:
        data = MLData.load()
        with self._lock:
            key = data.key()
            if self._cache is not None and self._cache_key == key and not force:
                return self._cache
            self.data = data
            cls_ds, reg_ds = tasks.build_invoice_datasets(data.invoices)
            bill_ds = tasks.build_bill_dataset(data.bills)
            reports = [
                self._run_task("invoice_late", cls_ds, data, min_train=80),
                self._run_task("invoice_days_late", reg_ds, data, min_train=80),
                self._run_task("learned_credit_score", cls_ds, data, min_train=80),
                self._run_task("bill_days_late", bill_ds, data, min_train=25),
                self._run_drivers(data),
            ]
            self._learned_weights(next(r for r in reports if r["task"] == "learned_credit_score"))
            verdicts = [r.get("comparison", {}).get("verdict") for r in reports if r.get("status") == "ok"]
            out = _clean(
                {
                    "mode": MODE,
                    "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
                    "principles": PRINCIPLES,
                    "data": {
                        "invoices": len(data.invoices), "customers": len({i.customer_id for i in data.invoices}),
                        "bills": len(data.bills), "vendors": len({b.vendor_id for b in data.bills}),
                        "ledger_months": len(data.gl_months()), "as_of": data.as_of, "data_end": data.data_end,
                        "caveat": "Bundled sample data. It shows the framework works, not how the models perform on real businesses.",
                    },
                    "summary": {"tasks": len(reports), "tested": len(verdicts), **{v: verdicts.count(v) for v in ("beats", "ties", "worse", "unclear")}},
                    "tasks": reports,
                    "registry": [
                        {k: r[k] for k in ("id", "task", "model", "label", "version", "trained_at", "rows", "data_fingerprint", "train_window")}
                        for r in sorted(self.registry.latest(), key=lambda r: (r["task"], r["model"]))
                    ],
                }
            )
            self._cache, self._cache_key = out, key
            return out

    # -- shadow predictions on open invoices ----------------------------------------
    def open_invoice_predictions(self, limit: int = 15) -> Dict[str, Any]:
        overview = self.overview()
        data = self.data
        cls_task = next(t for t in overview["tasks"] if t["task"] == "invoice_late")
        reg_task = next(t for t in overview["tasks"] if t["task"] == "invoice_days_late")
        if cls_task.get("status") != "ok" or data is None:
            return {"available": False, "reason": "The models need more history before they can score open invoices."}
        cls_est, cls_feats = self.estimators[f"invoice_late.{cls_task['comparison']['best_model']}"]
        reg_est, reg_feats = self.estimators[f"invoice_days_late.{reg_task['comparison']['best_model']}"] if reg_task.get("status") == "ok" else (None, None)
        by_customer: Dict[str, List[ar.Invoice]] = {}
        for i in data.invoices:
            by_customer.setdefault(i.customer_id, []).append(i)
        rows = []
        for inv in data.invoices:
            unpaid = inv.payment_date is None or inv.payment_date > data.as_of
            if not unpaid or inv.invoice_date > data.as_of or inv.due_date <= data.as_of:
                continue  # only invoices that are not yet due: for the rest, lateness is already known
            f = tasks.invoice_features(by_customer[inv.customer_id], inv, data.as_of)
            p = float(cls_est.predict_proba(np.array([[f[n] for n in cls_feats]]))[0, 1])
            days = float(reg_est.predict(np.array([[f[n] for n in reg_feats]]))[0]) if reg_est is not None else None
            rows.append({"invoice_id": inv.invoice_id, "customer_id": inv.customer_id, "amount": inv.open_amount or inv.amount,
                         "due_date": inv.due_date, "probability_late": p, "expected_days_late": days,
                         "simple_rule_days_late": f["avg_days_late"], "credit_score": f["score"]})
        total = sum(r["amount"] for r in rows)
        rows.sort(key=lambda r: -r["amount"] * r["probability_late"])
        return _clean(
            {
                "available": True, "as_of": data.as_of, "mode": MODE,
                "model": {"late": cls_task["comparison"]["best_model"], "days": reg_task.get("comparison", {}).get("best_model")},
                "summary": {
                    "invoices": len(rows), "amount": total,
                    "expected_late_amount": sum(r["amount"] * r["probability_late"] for r in rows),
                    "simple_rule_late_amount": sum(r["amount"] for r in rows if r["simple_rule_days_late"] > tasks.LATE_DAYS),
                },
                "invoices": rows[:limit],
                "note": "Invoices that are already past due are excluded: their lateness is known. This does not change the cash flow forecast.",
            }
        )


_service: Optional[Service] = None


def get_service() -> Service:
    global _service
    if _service is None:
        _service = Service()
    return _service
