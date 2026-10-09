"""Datasets, time-aware validation, metrics, drift checks and the model registry."""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import numpy as np

SEED = 7


# --------------------------------------------------------------------------- #
# Datasets
# --------------------------------------------------------------------------- #


@dataclass
class Row:
    id: str
    group: str  # whole groups (a customer, a vendor) are resampled together for confidence ranges
    time: dt.date  # when the prediction would have been made; features use only what was known then
    known_at: dt.date  # when the outcome became known; a row can train a model only after this date
    features: Dict[str, float]
    target: float
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Dataset:
    name: str
    kind: str  # "classification" or "regression"
    rows: List[Row]
    feature_names: List[str]
    notes: List[str] = field(default_factory=list)

    def matrix(self, rows: Sequence[Row], names: Sequence[str]) -> np.ndarray:
        return np.array([[r.features.get(n, 0.0) for n in names] for r in rows], dtype=float).reshape(len(rows), len(names))

    def target(self, rows: Sequence[Row]) -> np.ndarray:
        return np.array([r.target for r in rows], dtype=float)

    def fingerprint(self) -> str:
        h = hashlib.sha1()
        for r in sorted(self.rows, key=lambda r: r.id):
            h.update(f"{r.id}|{r.time}|{r.target:.4f}|".encode())
            h.update(("|".join(f"{r.features.get(n, 0.0):.4f}" for n in self.feature_names)).encode())
        return h.hexdigest()[:12]


@dataclass
class ModelSpec:
    name: str
    make: Callable[[], Any]
    features: List[str]
    label: str = ""


@dataclass
class BaselineSpec:
    name: str
    # (train_rows, test_row) -> prediction. For classification higher means riskier.
    predict: Callable[[Sequence[Row], Row], float]
    is_probability: bool = False
    primary: bool = False


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #


def auc(y: np.ndarray, score: np.ndarray) -> Optional[float]:
    from scipy.stats import rankdata

    y = np.asarray(y).astype(int)
    pos = int(y.sum())
    neg = len(y) - pos
    if pos == 0 or neg == 0:
        return None
    ranks = rankdata(score)
    return float((ranks[y == 1].sum() - pos * (pos + 1) / 2.0) / (pos * neg))


def brier(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def logloss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def mae(y: np.ndarray, p: np.ndarray) -> float:
    return float(np.mean(np.abs(np.asarray(p) - np.asarray(y))))


def rmse(y: np.ndarray, p: np.ndarray) -> float:
    return float(math.sqrt(np.mean((np.asarray(p) - np.asarray(y)) ** 2)))


def metric_fns(kind: str, probability: bool) -> Dict[str, Callable[[np.ndarray, np.ndarray], Optional[float]]]:
    if kind == "classification":
        fns: Dict[str, Callable] = {"auc": auc}
        if probability:
            fns |= {"brier": brier, "logloss": logloss}
        return fns
    return {"mae": mae, "rmse": rmse}


PRIMARY = {"classification": ("auc", True), "regression": ("mae", False)}  # (metric, higher_is_better)


def calibration_bins(y: np.ndarray, p: np.ndarray, bins: int = 5) -> List[Dict[str, float]]:
    order = np.argsort(p)
    out = []
    for chunk in np.array_split(order, bins):
        if len(chunk):
            out.append({"count": int(len(chunk)), "predicted": float(np.mean(p[chunk])), "observed": float(np.mean(y[chunk]))})
    return out


# --------------------------------------------------------------------------- #
# Walk-forward validation
# --------------------------------------------------------------------------- #


@dataclass
class Folds:
    folds: List[Dict[str, Any]]
    test_rows: List[Row]
    train_sets: List[List[Row]]
    test_sets: List[List[Row]]


def make_folds(rows: Sequence[Row], block_days: int = 30, min_train: int = 60, min_test: int = 10) -> Folds:
    """Expanding-window folds. A fold's training rows are only those whose outcome was already known before its
    test block begins, so nothing about the future leaks into training."""
    rows = sorted(rows, key=lambda r: r.time)
    if not rows:
        return Folds([], [], [], [])
    start, end = rows[0].time, rows[-1].time
    folds, train_sets, test_sets, all_test = [], [], [], []
    edge = start + dt.timedelta(days=block_days)
    while edge <= end:
        block_end = edge + dt.timedelta(days=block_days)
        train = [r for r in rows if r.known_at < edge]
        test = [r for r in rows if edge <= r.time < block_end]
        if len(train) >= min_train and len(test) >= min_test:
            folds.append({"test_start": edge, "test_end": block_end, "train_rows": len(train), "test_rows": len(test)})
            train_sets.append(train)
            test_sets.append(test)
            all_test.extend(test)
        edge = block_end
    return Folds(folds, all_test, train_sets, test_sets)


def _fit_predict(spec: ModelSpec, ds: Dataset, train: Sequence[Row], test: Sequence[Row], kind: str) -> np.ndarray:
    est = spec.make()
    X, y = ds.matrix(train, spec.features), ds.target(train)
    if kind == "classification" and len(set(y.tolist())) < 2:
        return np.full(len(test), float(y.mean()) if len(y) else 0.5)
    est.fit(X, y)
    Xt = ds.matrix(test, spec.features)
    if kind == "classification":
        return est.predict_proba(Xt)[:, 1]
    return est.predict(Xt)


def evaluate(
    ds: Dataset,
    models: Sequence[ModelSpec],
    baselines: Sequence[BaselineSpec],
    block_days: int = 30,
    min_train: int = 60,
    reps: int = 300,
) -> Dict[str, Any]:
    """Walk forward through time, then score every model and baseline on the pooled out-of-time predictions."""
    kind = ds.kind
    folds = make_folds(ds.rows, block_days, min_train)
    if not folds.folds:
        return {"status": "insufficient_data", "folds": []}

    preds: Dict[str, List[float]] = {m.name: [] for m in models} | {b.name: [] for b in baselines}
    for train, test in zip(folds.train_sets, folds.test_sets):
        for m in models:
            preds[m.name].extend(_fit_predict(m, ds, train, test, kind).tolist())
        for b in baselines:
            preds[b.name].extend(b.predict(train, r) for r in test)

    test_rows = [r for fold in folds.test_sets for r in fold]
    y = ds.target(test_rows)
    P = {k: np.asarray(v, dtype=float) for k, v in preds.items()}
    prob_flag = {m.name: True for m in models} | {b.name: b.is_probability for b in baselines}
    primary_metric, higher = PRIMARY[kind]

    groups: Dict[str, List[int]] = {}
    for i, r in enumerate(test_rows):
        groups.setdefault(r.group, []).append(i)
    keys = sorted(groups)
    arrays = [np.array(groups[k]) for k in keys]
    rng = np.random.default_rng(SEED)

    fns = {name: metric_fns(kind, prob_flag[name]) for name in P}
    point = {name: {m: fn(y, P[name]) for m, fn in fns[name].items()} for name in P}
    boot: Dict[str, Dict[str, List[float]]] = {name: {m: [] for m in fns[name]} for name in P}
    for _ in range(reps):  # resample whole customers/vendors: their rows are not independent
        idx = np.concatenate([arrays[j] for j in rng.integers(0, len(arrays), len(arrays))])
        yy = y[idx]
        for name in P:
            for m, fn in fns[name].items():
                v = fn(yy, P[name][idx])
                if v is not None:
                    boot[name][m].append(v)

    def ci(vals: List[float]) -> Optional[List[float]]:
        return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))] if len(vals) >= 30 else None

    return {
        "status": "ok",
        "folds": folds.folds,
        "test_rows": test_rows,
        "y": y,
        "preds": P,
        "point": point,
        "ci": {name: {m: ci(v) for m, v in boot[name].items()} for name in P},
        "boot": boot,
        "primary_metric": primary_metric,
        "higher_is_better": higher,
    }


def paired_difference(ds: Dataset, ev: Dict[str, Any], a: str, b: str, reps: int = 300) -> Dict[str, Any]:
    """Primary metric of ``a`` minus ``b`` with a customer-level confidence range (same resamples for both)."""
    metric = ev["primary_metric"]
    fn = metric_fns(ds.kind, True)[metric]
    y, P, rows = ev["y"], ev["preds"], ev["test_rows"]
    groups: Dict[str, List[int]] = {}
    for i, r in enumerate(rows):
        groups.setdefault(r.group, []).append(i)
    arrays = [np.array(v) for _, v in sorted(groups.items())]
    rng = np.random.default_rng(SEED + 1)
    diffs = []
    for _ in range(reps):
        idx = np.concatenate([arrays[j] for j in rng.integers(0, len(arrays), len(arrays))])
        va, vb = fn(y[idx], P[a][idx]), fn(y[idx], P[b][idx])
        if va is not None and vb is not None:
            diffs.append(va - vb)
    point = fn(y, P[a]) - fn(y, P[b])
    lo, hi = (float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))) if len(diffs) >= 30 else (None, None)
    return {"metric": metric, "difference": float(point), "ci_low": lo, "ci_high": hi}


def verdict(diff: Dict[str, Any], higher_is_better: bool) -> str:
    lo, hi, d = diff["ci_low"], diff["ci_high"], diff["difference"]
    if lo is None or hi is None:
        return "unclear"
    better = (lo > 0) if higher_is_better else (hi < 0)
    worse = (hi < 0) if higher_is_better else (lo > 0)
    return "beats" if better else "worse" if worse else "ties"


# --------------------------------------------------------------------------- #
# Drift
# --------------------------------------------------------------------------- #


def psi(reference: np.ndarray, current: np.ndarray, bins: int = 8) -> Optional[float]:
    """Population stability index: how far the recent values of a feature have moved from what the model trained on."""
    if len(reference) < 20 or len(current) < 10:
        return None
    edges = np.unique(np.quantile(reference, np.linspace(0, 1, bins + 1)))
    if len(edges) < 3:
        return 0.0
    edges[0], edges[-1] = -np.inf, np.inf
    r = np.histogram(reference, edges)[0] / len(reference)
    c = np.histogram(current, edges)[0] / len(current)
    r, c = np.clip(r, 1e-4, None), np.clip(c, 1e-4, None)
    return float(np.sum((c - r) * np.log(c / r)))


def drift_report(ds: Dataset, features: Sequence[str], recent_days: int = 45) -> List[Dict[str, Any]]:
    if not ds.rows:
        return []
    cutoff = max(r.time for r in ds.rows) - dt.timedelta(days=recent_days)
    ref = [r for r in ds.rows if r.time < cutoff]
    cur = [r for r in ds.rows if r.time >= cutoff]
    out = []
    for f in features:
        v = psi(np.array([r.features.get(f, 0.0) for r in ref]), np.array([r.features.get(f, 0.0) for r in cur]))
        if v is not None:
            out.append({"feature": f, "psi": v, "status": "shifted" if v >= 0.25 else "watch" if v >= 0.1 else "stable"})
    return sorted(out, key=lambda d: -d["psi"])


def importances(est: Any, names: Sequence[str]) -> List[Dict[str, Any]]:
    model = est.steps[-1][1] if hasattr(est, "steps") else est
    if hasattr(model, "feature_importances_"):
        w = np.asarray(model.feature_importances_, dtype=float)
    elif hasattr(model, "coef_"):
        w = np.abs(np.asarray(model.coef_, dtype=float)).reshape(-1)
        if len(w) != len(names):
            return []
    else:
        return []
    total = w.sum() or 1.0
    return sorted(({"feature": n, "weight": float(x / total)} for n, x in zip(names, w)), key=lambda d: -d["weight"])[:10]


# --------------------------------------------------------------------------- #
# Registry
# --------------------------------------------------------------------------- #


class Registry:
    """Every trained model is saved with what it was trained on and how it scored, so any prediction can be traced."""

    def __init__(self, directory: Optional[str] = None):
        base = directory or os.getenv("MODEL_STORE_DIR") or str(Path(__file__).resolve().parent.parent / "models_store")
        self.dir = Path(base)
        self.records: List[Dict[str, Any]] = []
        self._load()

    def _load(self) -> None:
        try:
            for p in sorted(self.dir.glob("*.json")):
                self.records.append(json.loads(p.read_text()))
        except Exception:
            self.records = []

    def next_version(self, task: str, model: str) -> int:
        return 1 + sum(1 for r in self.records if r["task"] == task and r["model"] == model)

    def save(self, record: Dict[str, Any], estimator: Any = None) -> Dict[str, Any]:
        record = dict(record)
        record["version"] = self.next_version(record["task"], record["model"])
        record["id"] = f"{record['task']}.{record['model']}.v{record['version']}"
        record["trained_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        self.records.append(record)
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / f"{record['id']}.json").write_text(json.dumps(record, default=str, indent=2))
            if estimator is not None:
                import joblib

                joblib.dump(estimator, self.dir / f"{record['id']}.joblib")
        except Exception:
            pass  # saving is best-effort; the in-memory registry still works
        return record

    def latest(self) -> List[Dict[str, Any]]:
        seen: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for r in self.records:
            seen[(r["task"], r["model"])] = r
        return list(seen.values())

    def history(self, task: str, model: str) -> List[Dict[str, Any]]:
        return [r for r in self.records if r["task"] == task and r["model"] == model]
