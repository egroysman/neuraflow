"""Live macro indicators from FRED (St. Louis Fed), with a cache.

No API key is needed: FRED serves each series as CSV. Results are cached for
six hours. If a refresh fails, the last good data is returned and marked
``stale``; if there has never been a successful fetch the status is
``unavailable`` and *no numbers are invented*.

The suggestions are plain arithmetic on the latest data and are only ever
applied when the user turns the macro overlay on.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List, Optional, Tuple

CACHE_TTL_SECONDS = 6 * 3600
FETCH_TIMEOUT_SECONDS = 10
HISTORY_YEARS = 6
TREND_NORM_PCT = 2.0  # inflation target and long-run real growth used for the suggestions

# key: (FRED id, label, kind, observations per year used for year-on-year, unit)
SERIES: Dict[str, Tuple[str, str, str, int, str]] = {
    "prime": ("DPRIME", "Bank prime loan rate", "level", 0, "%"),
    "fed_funds": ("FEDFUNDS", "Federal funds rate", "level", 0, "%"),
    "treasury_10y": ("DGS10", "10-year Treasury yield", "level", 0, "%"),
    "cpi": ("CPIAUCSL", "Inflation (CPI, year over year)", "yoy", 12, "%"),
    "unemployment": ("UNRATE", "Unemployment rate", "level", 0, "%"),
    "gdp": ("GDPC1", "Real GDP growth (year over year)", "yoy", 4, "%"),
}

_cache: Dict[str, Any] = {"data": None, "fetched_at": 0.0, "error": None}
_lock = threading.Lock()


def _fetch_csv(series_id: str) -> str:
    start = (dt.date.today() - dt.timedelta(days=365 * HISTORY_YEARS + 400)).isoformat()
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}&cosd={start}"
    req = urllib.request.Request(url, headers={"User-Agent": "neuraflow-cashflow/1.0"})
    with urllib.request.urlopen(req, timeout=FETCH_TIMEOUT_SECONDS) as resp:  # noqa: S310 (fixed https host)
        return resp.read().decode("utf-8")


def parse_csv(text: str) -> List[Tuple[dt.date, float]]:
    points: List[Tuple[dt.date, float]] = []
    reader = csv.reader(io.StringIO(text))
    next(reader, None)  # header
    for row in reader:
        if len(row) < 2 or row[1] in ("", "."):
            continue
        try:
            points.append((dt.date.fromisoformat(row[0]), float(row[1])))
        except ValueError:
            continue
    return points


def _month_end_series(points: List[Tuple[dt.date, float]]) -> List[Tuple[dt.date, float]]:
    """Keep the last observation of each month (daily series become monthly)."""
    last: Dict[Tuple[int, int], Tuple[dt.date, float]] = {}
    for d, v in points:
        last[(d.year, d.month)] = (d, v)
    return [last[k] for k in sorted(last)]


def _yoy(points: List[Tuple[dt.date, float]], lag: int) -> List[Tuple[dt.date, float]]:
    out = []
    for i in range(lag, len(points)):
        prior = points[i - lag][1]
        if prior:
            out.append((points[i][0], (points[i][1] / prior - 1.0) * 100.0))
    return out


def _value_a_year_before(points: List[Tuple[dt.date, float]]) -> Optional[Tuple[dt.date, float]]:
    if not points:
        return None
    target = points[-1][0] - dt.timedelta(days=365)
    candidates = [p for p in points if p[0] <= target]
    return candidates[-1] if candidates else None


def build_series(key: str, text: str) -> Optional[Dict[str, Any]]:
    fred_id, label, kind, lag, unit = SERIES[key]
    points = parse_csv(text)
    if kind == "yoy":
        points = _yoy(points, lag)
    else:
        points = _month_end_series(points)
    if not points:
        return None
    latest = points[-1]
    prior = _value_a_year_before(points)
    cutoff = latest[0] - dt.timedelta(days=365 * 3)
    return {
        "key": key,
        "fred_id": fred_id,
        "label": label,
        "unit": unit,
        "latest": round(latest[1], 2),
        "latest_date": latest[0],
        "year_ago": round(prior[1], 2) if prior else None,
        "change_12m": round(latest[1] - prior[1], 2) if prior else None,
        "history": [{"date": d, "value": round(v, 3)} for d, v in points if d >= cutoff],
    }


def suggestions(series: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    """Overlay inputs implied by the latest data (all relative to a neutral norm)."""
    out: Dict[str, Any] = {}
    rate = series.get("prime") or series.get("fed_funds")
    if rate and rate.get("change_12m") is not None:
        out["rate_change_pts"] = {
            "value": rate["change_12m"],
            "basis": f"{rate['label']} moved {rate['change_12m']:+.2f} pts over the last 12 months",
        }
    cpi = series.get("cpi")
    if cpi:
        out["cost_inflation_pct"] = {
            "value": round(cpi["latest"] - TREND_NORM_PCT, 2),
            "basis": f"CPI is {cpi['latest']:.1f}% year over year vs a {TREND_NORM_PCT:.0f}% norm",
        }
    gdp = series.get("gdp")
    if gdp:
        out["demand_growth_pct"] = {
            "value": round(gdp["latest"] - TREND_NORM_PCT, 2),
            "basis": f"Real GDP is growing {gdp['latest']:.1f}% year over year vs a {TREND_NORM_PCT:.0f}% norm",
        }
    return out


def _refresh() -> Tuple[Dict[str, Dict[str, Any]], List[str]]:
    keys = list(SERIES)

    def one(key: str):
        try:
            return key, build_series(key, _fetch_csv(SERIES[key][0])), None
        except Exception as exc:  # network, parse, HTTP: report per series
            return key, None, f"{SERIES[key][0]}: {type(exc).__name__}"

    with ThreadPoolExecutor(max_workers=len(keys)) as pool:
        results = list(pool.map(one, keys))
    data = {k: s for k, s, _ in results if s}
    errors = [e for _, _, e in results if e]
    return data, errors


def get_macro(force: bool = False) -> Dict[str, Any]:
    now = time.time()
    with _lock:
        fresh = _cache["data"] and now - _cache["fetched_at"] < CACHE_TTL_SECONDS
        if fresh and not force:
            return _payload("live", _cache["data"], _cache["fetched_at"], _cache["error"])
        data, errors = _refresh()
        if data:
            # Merge so one failing series keeps its previous value instead of vanishing.
            merged = dict(_cache["data"] or {})
            merged.update(data)
            _cache.update(data=merged, fetched_at=now, error=errors or None)
            return _payload("live" if not errors else "partial", merged, now, errors or None)
        if _cache["data"]:
            _cache["error"] = errors
            return _payload("stale", _cache["data"], _cache["fetched_at"], errors)
        _cache["error"] = errors
        return _payload("unavailable", {}, None, errors)


def _payload(status: str, data: Dict[str, Dict[str, Any]], fetched_at: Optional[float], errors) -> Dict[str, Any]:
    return {
        "status": status,
        "source": "FRED, Federal Reserve Bank of St. Louis",
        "fetched_at": dt.datetime.fromtimestamp(fetched_at, dt.timezone.utc).isoformat() if fetched_at else None,
        "series": [data[k] for k in SERIES if k in data],
        "suggestions": suggestions(data),
        "errors": errors or [],
        "norm_pct": TREND_NORM_PCT,
    }


def reset_cache() -> None:
    with _lock:
        _cache.update(data=None, fetched_at=0.0, error=None)
