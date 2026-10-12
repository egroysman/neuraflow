"""Connect a source to a dataset: preview, map, check, load, refresh on a schedule.

Loaded data is saved as a snapshot, so the forecast never waits on a warehouse or SFTP server.
Until the first dataset is saved the bundled sample is used. After that, only what you loaded is
used: a dataset with no source is empty rather than quietly filled with sample data.
"""
from __future__ import annotations

import datetime as dt
import decimal
import os
import re
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

from . import readers, store
from .mapping import apply_mapping, sample_values, suggest_mapping, validate
from .parsing import is_blank
from .readers import SourceError, Table
from .schemas import DATASETS, ORDER

PREVIEW_ROWS = 8
_refresh_lock = threading.Lock()


def jsonable(v: Any) -> Any:
    if v is None or isinstance(v, (str, int, float, bool)):
        return v
    if isinstance(v, (dt.datetime, dt.date)):
        return v.isoformat()
    if isinstance(v, decimal.Decimal):
        return float(v)
    if isinstance(v, bytes):
        return "<binary>"
    return str(v)


# ------------------------------------------------------------------ sources

def _reader(conn: Dict[str, Any]):
    t, p = conn["type"], conn["params"]
    if t == "snowflake":
        return readers.snowflake_reader(p)
    if t == "databricks":
        return readers.databricks_reader(p)
    if t == "sftp":
        return readers.SftpReader(p)
    raise SourceError("Unknown connection type.")


def source_label(src: Dict[str, Any]) -> str:
    try:
        if src["kind"] == "upload":
            u = store._read_json("uploads.json", {}).get(src["upload_id"], {})
            return f"Upload: {u.get('filename', 'file')}" + (f" ({src['object']})" if src.get("object") and src["object"] != "file" else "")
        conn = store.get_connection(src["connection_id"])
        what = src.get("object") or ""
        if what.startswith("sql:"):
            what = "custom query"
        return f"{conn['name']}: {what}"
    except SourceError:
        return "Source unavailable"


def read_source(src: Dict[str, Any], limit: int = readers.ROW_LIMIT) -> Table:
    if src.get("kind") == "upload":
        up = store.get_upload(src["upload_id"])
        return readers.read_file_bytes(up["bytes"], up["filename"], src.get("object") if src.get("object") != "file" else None, limit, src.get("header_row"))
    if src.get("kind") == "connection":
        conn = store.get_connection(src["connection_id"])
        rd = _reader(conn)
        obj = src.get("object") or ""
        if not obj:
            raise SourceError("Choose a table, sheet or file.")
        if conn["type"] == "sftp":
            return rd.read(obj, limit, src.get("sheet"), src.get("header_row"))
        return rd.read(obj, limit)
    raise SourceError("Choose where the data comes from.")


def list_objects(src: Dict[str, Any]) -> List[Dict[str, Any]]:
    if src.get("kind") == "upload":
        up = store.get_upload(src["upload_id"])
        return readers.file_objects(up["bytes"], up["filename"])
    conn = store.get_connection(src["connection_id"])
    return _reader(conn).objects()


def test_connection(cid: str) -> Dict[str, Any]:
    conn = store.get_connection(cid)
    rd = _reader(conn)
    if conn["type"] == "sftp":
        try:
            rd.test()
        except SourceError as e:
            if str(e).startswith("HOSTKEY:"):
                return {"ok": False, "needs_host_key": True, "host_key_sha256": str(e)[8:],
                        "message": "This server's identity has not been confirmed yet. Check the fingerprint with whoever runs the server, then pin it."}
            raise
    else:
        rd.test()
    return {"ok": True, "message": "Connected."}


def observe_host_key(params: Dict[str, Any]) -> str:
    return readers.SftpReader({**params, "username": params.get("username") or "x", "password": params.get("password") or "x"}).observed_fingerprint()


# ------------------------------------------------------------------ analyse / save

def _journal_extra(key: str) -> Optional[Dict[str, Any]]:
    if key != "gl_journal":
        return None
    accts = store.read_snapshot("gl_accounts")
    return {"account_ids": {a["AccountID"] for a in accts}} if accts else None


def analyze(key: str, src: Dict[str, Any], mapping: Optional[Dict[str, Optional[str]]] = None, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    ds = DATASETS[key]
    cols, rows, truncated = read_source(src)
    sug = suggest_mapping(ds, cols, rows)
    used = mapping if mapping is not None else {k: v["column"] for k, v in sug.items()}
    out, report = apply_mapping(key, rows, used, options or {})
    val = validate(key, out, report, used, _journal_extra(key))
    if truncated:
        val["issues"].append({"level": "warning", "message": f"Only the first {readers.ROW_LIMIT:,} rows were read."})
    return {
        "dataset": key, "columns": cols, "row_count": len(rows), "truncated": truncated,
        "raw_sample": [{c: jsonable(r.get(c)) for c in cols} for r in rows[:PREVIEW_ROWS]],
        "fields": [{"name": f.name, "label": f.label, "kind": f.kind, "required": f.required, "help": f.help} for f in ds.fields],
        "at_least_one_of": [list(g) for g in ds.at_least_one_of],
        "suggestions": {k: {**v, "samples": sample_values(rows, v["column"])} for k, v in sug.items()},
        "mapping": used, "options": options or {},
        "mapped_sample": out[:PREVIEW_ROWS], "report": {k: v for k, v in report.items() if k != "inferred"},
        "classified": ([{"AccountID": a["AccountID"], "AccountName": a["AccountName"], "AccountType": a["AccountType"], "ModelLine": a["ModelLine"], "inferred": a["AccountID"] in report["inferred"]} for a in out]
                       if key == "gl_accounts" else None),
        "validation": val,
    }


def _normalise(key: str, src: Dict[str, Any], mapping: Dict[str, Optional[str]], options: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    cols, rows, truncated = read_source(src)
    missing = [c for c in mapping.values() if c and c not in cols]
    if missing:
        raise SourceError("These columns are no longer in the source: " + ", ".join(sorted(set(missing))) + ". Open the dataset and map them again.")
    out, report = apply_mapping(key, rows, mapping, options)
    val = validate(key, out, report, mapping, _journal_extra(key))
    return out, report, val


def _stats_range(key: str, rows: List[Dict[str, Any]]) -> Optional[List[str]]:
    col = {"invoices": "InvoiceDate", "bills": "BillDate", "gl_journal": "Date"}.get(key)
    vals = sorted(r[col] for r in rows if r.get(col)) if col else []
    return [vals[0], vals[-1]] if vals else None


def save_dataset(key: str, src: Dict[str, Any], mapping: Dict[str, Optional[str]], options: Optional[Dict[str, Any]] = None, schedule: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if key not in DATASETS:
        raise SourceError("Unknown dataset.")
    options = options or {}
    mapping = {k: v for k, v in mapping.items() if v}
    out, report, val = _normalise(key, src, mapping, options)
    if not val["ok"]:
        raise SourceError("Not loaded: " + " ".join(i["message"] for i in val["issues"] if i["level"] == "error"))
    sched = parse_schedule(schedule)
    with store.LOCK:
        prev = store.get_configs().get(key, {})
        store.write_snapshot(key, out)
        store.put_config(key, {
            "source": src, "mapping": mapping, "options": options, "schedule": sched, "version": int(prev.get("version", 0)) + 1,
            "saved_at": time.time(), "label": source_label(src),
            "last_run": {"at": time.time(), "ok": True, "rows_in": report["rows_in"], "rows_out": report["rows_out"], "message": "Loaded.", "trigger": "save"},
            "stats": {**val["stats"], "date_range": _stats_range(key, out)},
        })
    return {"ok": True, "rows": len(out), "validation": val}


def refresh_dataset(key: str, trigger: str = "manual") -> Dict[str, Any]:
    """Re-read the saved source. Bad or much smaller data never replaces what is already loaded."""
    with _refresh_lock:
        cfg = store.get_configs().get(key)
        if not cfg:
            raise SourceError("That dataset has no source yet.")
        prev_rows = int((cfg.get("last_run") or {}).get("rows_out") or 0)
        now = time.time()
        try:
            out, report, val = _normalise(key, cfg["source"], cfg["mapping"], cfg.get("options") or {})
            if not val["ok"]:
                raise SourceError("The new data failed its checks: " + " ".join(i["message"] for i in val["issues"] if i["level"] == "error"))
            if prev_rows >= 20 and len(out) < 0.5 * prev_rows:
                raise SourceError(f"The new data has {len(out)} rows, down from {prev_rows}. Kept the previous data. Check the source, then refresh again.")
            store.write_snapshot(key, out)
            run = {"at": now, "ok": True, "rows_in": report["rows_in"], "rows_out": len(out), "message": "Refreshed.", "trigger": trigger}
            cfg["stats"] = {**val["stats"], "date_range": _stats_range(key, out)}
        except SourceError as e:
            msg = str(e)
            if msg.startswith("HOSTKEY:"):
                msg = "The SFTP server's identity is not pinned. Pin its fingerprint on the connection."
            run = {"at": now, "ok": False, "rows_in": 0, "rows_out": prev_rows, "message": msg[:400], "trigger": trigger}
        except Exception as e:  # noqa: BLE001
            run = {"at": now, "ok": False, "rows_in": 0, "rows_out": prev_rows, "message": f"Unexpected error: {type(e).__name__}", "trigger": trigger}
        with store.LOCK:
            cur = store.get_configs().get(key)
            if cur:  # not reset or re-mapped while we were reading
                cur["last_run"] = run
                if run["ok"]:
                    cur["stats"] = cfg["stats"]
                store.put_config(key, cur)
        return run


def set_schedule(key: str, schedule: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    cfg = store.get_configs().get(key)
    if not cfg:
        raise SourceError("That dataset has no source yet.")
    cfg["schedule"] = parse_schedule(schedule)
    store.put_config(key, cfg)
    return cfg["schedule"]


def reset_dataset(key: str) -> None:
    with store.LOCK:
        store.put_config(key, None)
        store.delete_snapshot(key)


def reset_all() -> None:
    for k in ORDER:
        reset_dataset(k)


# ------------------------------------------------------------------ what the forecast reads

def custom_mode() -> bool:
    return bool(store.get_configs())


def rows_for(key: str) -> Optional[List[Dict[str, Any]]]:
    """None while the bundled sample is in use. Otherwise the loaded rows (empty if this dataset has no source)."""
    if not custom_mode():
        return None
    if key not in store.get_configs():
        return []
    return store.read_snapshot(key) or []


# ------------------------------------------------------------------ schedule

_AT = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


def parse_schedule(s: Optional[Any]) -> Dict[str, Any]:
    if not s:
        return {"mode": "off"}
    if isinstance(s, str):
        s = s.strip().lower()
        m = re.fullmatch(r"every[: ]*(\d+)\s*(m|min|h|hr|hour|hours)?", s)
        if m:
            n = int(m.group(1)) * (60 if (m.group(2) or "m").startswith("h") else 1)
            s = {"mode": "interval", "every_minutes": n}
        elif s.startswith("daily"):
            s = {"mode": "daily", "at": (s.split("@", 1) + ["06:00"])[1] if "@" in s else "06:00"}
        else:
            s = {"mode": "off"}
    mode = s.get("mode", "off")
    if mode == "interval":
        n = int(s.get("every_minutes") or 0)
        if n < 15:
            raise SourceError("Refresh no more often than every 15 minutes.")
        return {"mode": "interval", "every_minutes": min(n, 7 * 24 * 60)}
    if mode == "daily":
        at = str(s.get("at") or "06:00")
        if not _AT.match(at):
            raise SourceError("Use a time like 06:00.")
        tz = s.get("timezone") or os.getenv("INGEST_TIMEZONE") or "UTC"
        try:
            from zoneinfo import ZoneInfo

            ZoneInfo(tz)
        except Exception:  # noqa: BLE001
            raise SourceError(f"Unknown time zone '{tz}'.")
        h, m = at.split(":")
        return {"mode": "daily", "at": f"{int(h):02d}:{m}", "timezone": tz}
    return {"mode": "off"}


def next_run(cfg: Dict[str, Any], now: Optional[float] = None) -> Optional[float]:
    s = cfg.get("schedule") or {"mode": "off"}
    last = float((cfg.get("last_run") or {}).get("at") or cfg.get("saved_at") or 0)
    if s["mode"] == "interval":
        return last + s["every_minutes"] * 60
    if s["mode"] == "daily":
        from zoneinfo import ZoneInfo

        tz = ZoneInfo(s.get("timezone") or "UTC")
        h, m = (int(x) for x in s["at"].split(":"))
        base = dt.datetime.fromtimestamp(last, tz)
        cand = base.replace(hour=h, minute=m, second=0, microsecond=0)
        if cand <= base:
            cand += dt.timedelta(days=1)
        return cand.timestamp()
    return None


def due_datasets(now: Optional[float] = None) -> List[str]:
    now = now or time.time()
    out = []
    for k, cfg in store.get_configs().items():
        nr = next_run(cfg)
        if nr is not None and nr <= now:
            out.append(k)
    return out


# ------------------------------------------------------------------ ghost mode (SFTP drop folder)

def ghost_settings() -> Optional[Dict[str, Any]]:
    """Set SFTP_* and SFTP_PATTERN_<DATASET> on the server and NeuraFlow loads on its own."""
    if "env:sftp" not in store.env_connections():
        return None
    pats = {k: os.getenv(f"SFTP_PATTERN_{k.upper()}") for k in ORDER}
    pats = {k: v.strip() for k, v in pats.items() if v and v.strip()}
    if not pats:
        return None
    return {"patterns": pats, "schedule": parse_schedule(os.getenv("SFTP_SCHEDULE") or "daily@06:00")}


def _ghost_state() -> Dict[str, Any]:
    return store._read_json("ghost.json", {})


def ghost_scan(retry_after: float = 3600.0) -> Dict[str, Any]:
    """Load any dataset that has a file pattern but no source yet. Only loads when the mapping is
    unambiguous and the checks pass; otherwise it records what to review and leaves the dataset alone."""
    g = ghost_settings()
    if not g:
        return {}
    state = _ghost_state()
    configs = store.get_configs()
    for key in ORDER:  # accounts before journal
        pat = g["patterns"].get(key)
        if not pat or key in configs:
            continue
        last = state.get(key)
        if last and time.time() - last["at"] < retry_after and not last.get("ok"):
            continue
        src = {"kind": "connection", "connection_id": "env:sftp", "object": pat}
        try:
            a = analyze(key, src)
            ds = DATASETS[key]
            unmapped = [f.label for f in ds.fields if f.required and f.name not in a["mapping"]]
            if unmapped:
                raise SourceError("Needs review: could not match " + ", ".join(unmapped) + ".")
            if not a["validation"]["ok"]:
                raise SourceError("Needs review: " + " ".join(i["message"] for i in a["validation"]["issues"] if i["level"] == "error"))
            save_dataset(key, src, a["mapping"], {}, g["schedule"])
            state[key] = {"at": time.time(), "ok": True, "message": f"Loaded from '{pat}'."}
            configs = store.get_configs()
        except SourceError as e:
            msg = str(e)
            if msg.startswith("HOSTKEY:"):
                msg = f"Pin this host key on the SFTP connection (SFTP_HOST_KEY_SHA256={msg[8:]})."
            state[key] = {"at": time.time(), "ok": False, "message": msg[:400]}
        except Exception as e:  # noqa: BLE001
            state[key] = {"at": time.time(), "ok": False, "message": f"Unexpected error: {type(e).__name__}"}
    store._write_json("ghost.json", state)
    return state


# ------------------------------------------------------------------ status

def status() -> Dict[str, Any]:
    cfgs = store.get_configs()
    ghost = ghost_settings()
    gstate = _ghost_state() if ghost else {}
    datasets = []
    for k in ORDER:
        ds, cfg = DATASETS[k], cfgs.get(k)
        row: Dict[str, Any] = {"key": k, "label": ds.label, "description": ds.description, "configured": bool(cfg)}
        if cfg:
            nr = next_run(cfg)
            row.update({"source": cfg.get("label"), "rows": (cfg.get("last_run") or {}).get("rows_out"), "last_run": cfg.get("last_run"),
                        "schedule": cfg.get("schedule"), "next_run": nr, "stats": cfg.get("stats"), "version": cfg.get("version"),
                        "source_kind": cfg["source"].get("kind"), "connection_id": cfg["source"].get("connection_id")})
        if ghost and k in ghost["patterns"]:
            row["ghost"] = {"pattern": ghost["patterns"][k], **({"state": gstate[k]} if k in gstate else {})}
        datasets.append(row)
    warnings: List[str] = []
    if cfgs:
        for k in ORDER:
            if k not in cfgs and k not in ("gl_journal", "gl_accounts", "payroll"):
                warnings.append(f"No source for {DATASETS[k].label.lower()}. It is treated as empty, not filled with sample data.")
        if ("gl_accounts" in cfgs) != ("gl_journal" in cfgs):
            warnings.append("The ledger needs both the chart of accounts and the journal lines. Until both are loaded it is not used.")
        ends = {k: (cfg.get("stats") or {}).get("date_range") for k, cfg in cfgs.items()}
        ends = {k: v[1] for k, v in ends.items() if v}
        if len(ends) >= 2:
            lo, hi = min(ends, key=ends.get), max(ends, key=ends.get)
            gap = (dt.date.fromisoformat(ends[hi]) - dt.date.fromisoformat(ends[lo])).days
            if gap > 45:
                warnings.append(f"{DATASETS[lo].label} ends {gap} days before {DATASETS[hi].label}. Check that both are current.")
    return {
        "mode": "custom" if cfgs else "sample",
        "datasets": datasets, "warnings": warnings,
        "admin": {"enabled": admin_enabled(), "token_required": bool(os.getenv("ADMIN_TOKEN"))},
        "encryption_ready": store.encryption_ready(),
        "storage": {"path_set": bool(os.getenv("INGEST_DIR")), "note": None if os.getenv("INGEST_DIR") else "Loaded data and saved connections are kept on the server's local disk and are lost when it redeploys, unless INGEST_DIR points at a persistent volume. Env-variable connections and ghost mode reload on their own."},
        "ghost": {"enabled": bool(ghost), "schedule": (ghost or {}).get("schedule")},
        "limits": {"max_upload_mb": readers.MAX_UPLOAD_BYTES // (1024 * 1024), "row_limit": readers.ROW_LIMIT},
    }


def admin_enabled() -> bool:
    return bool(os.getenv("ADMIN_TOKEN")) or os.getenv("ALLOW_OPEN_DATA_ADMIN", "").strip().lower() in ("1", "true", "yes", "on")


# ------------------------------------------------------------------ scheduler

_thread: Optional[threading.Thread] = None
_stop = threading.Event()


def _tick(last_ghost: List[float]) -> None:
    if ghost_settings() and time.time() - last_ghost[0] > 300:
        last_ghost[0] = time.time()
        try:
            ghost_scan()
        except Exception:  # noqa: BLE001
            pass
    for k in due_datasets():
        try:
            refresh_dataset(k, "schedule")
        except Exception:  # noqa: BLE001
            pass


def start_scheduler(interval: float = 30.0) -> None:
    global _thread
    if _thread and _thread.is_alive():
        return
    _stop.clear()
    last_ghost = [0.0]

    def loop():
        while not _stop.wait(interval):
            _tick(last_ghost)

    _thread = threading.Thread(target=loop, name="ingest-scheduler", daemon=True)
    _thread.start()


def stop_scheduler() -> None:
    _stop.set()
