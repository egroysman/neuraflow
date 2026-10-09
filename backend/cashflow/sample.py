"""Keep the bundled sample data current.

The sample CSVs were generated with their newest invoice on 2026-04-09. Left
alone, the forecast would start in the past and show a cash dip months ago.
These helpers move the sample forward by whole calendar months so it ends in
the current month. Whole months keep the general ledger's month boundaries
intact, and every gap inside a record (invoice to due date to payment) is kept
exactly, so payment behaviour is unchanged.

Only the bundled sample is moved. Data from DEFAULT_*_CSV_PATH, an upload or a
database is never touched. Set SAMPLE_REBASE=off to turn this off.
"""
from __future__ import annotations

import calendar
import datetime as dt
import os
from typing import Any, Dict, Iterable, List, Optional

# Newest invoice date in the bundled sample, the point the data was cut.
SAMPLE_ANCHOR = dt.date(2026, 4, 9)


def enabled() -> bool:
    return os.getenv("SAMPLE_REBASE", "on").strip().lower() not in ("off", "0", "false", "no")


def months_to_shift(today: Optional[dt.date] = None) -> int:
    """Whole months from the sample's end date to today (never negative)."""
    if not enabled():
        return 0
    today = today or dt.date.today()
    months = (today.year - SAMPLE_ANCHOR.year) * 12 + today.month - SAMPLE_ANCHOR.month
    if today.day < SAMPLE_ANCHOR.day:
        months -= 1
    return max(0, months)


def add_months(d: dt.date, months: int) -> dt.date:
    year, month0 = divmod(d.month - 1 + months, 12)
    year += d.year
    month = month0 + 1
    return dt.date(year, month, min(d.day, calendar.monthrange(year, month)[1]))


def _parse(value: Any) -> Optional[dt.date]:
    try:
        return dt.date.fromisoformat(str(value)[:10]) if value else None
    except ValueError:
        return None


def shift_rows(
    rows: Iterable[Dict[str, Any]],
    anchor_col: str,
    other_cols: Iterable[str] = (),
    months: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Move each row's ``anchor_col`` by whole months and the other dates by the same number of days."""
    k = months_to_shift() if months is None else months
    rows = [dict(r) for r in rows]
    if not k:
        return rows
    others = list(other_cols)
    for r in rows:
        old = _parse(r.get(anchor_col))
        if old is None:
            continue
        new = add_months(old, k)
        delta = new - old
        r[anchor_col] = new.isoformat()
        for c in others:
            d = _parse(r.get(c))
            if d is not None:
                r[c] = (d + delta).isoformat()
    return rows


def shift_each(rows: Iterable[Dict[str, Any]], cols: Iterable[str], months: Optional[int] = None) -> List[Dict[str, Any]]:
    """Move several independent date columns by whole months (journal lines, hire and term dates)."""
    k = months_to_shift() if months is None else months
    rows = [dict(r) for r in rows]
    if not k:
        return rows
    for r in rows:
        for c in cols:
            d = _parse(r.get(c))
            if d is not None:
                r[c] = add_months(d, k).isoformat()
    return rows


INVOICE_OTHERS = ("DueDate", "PaymentDate")
BILL_OTHERS = ("DueDate", "PaymentDate")
