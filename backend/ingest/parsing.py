"""Forgiving value parsing for dates and amounts that arrive in whatever form the source uses."""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Iterable, Optional, Sequence

_EXCEL_EPOCH = dt.date(1899, 12, 30)
_NULLS = {"", "none", "null", "nan", "nat", "n/a", "na", "-", "--"}
_MONTHS = {m: i for i, m in enumerate(["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}


def is_blank(v: Any) -> bool:
    if v is None:
        return True
    if isinstance(v, float) and v != v:
        return True
    return isinstance(v, str) and v.strip().lower() in _NULLS


def parse_number(v: Any) -> Optional[float]:
    """'$1,234.50', '(500)', '12%' , 1234, '1.234,50' -> float. Returns None if not a number."""
    if is_blank(v):
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    if hasattr(v, "__float__") and not isinstance(v, str):  # Decimal, numpy
        try:
            return float(v)
        except (TypeError, ValueError):
            return None
    s = str(v).strip()
    neg = False
    if s.startswith("(") and s.endswith(")"):
        neg, s = True, s[1:-1]
    if s.endswith("-") and s[:-1].replace(",", "").replace(".", "").isdigit():  # trailing minus (SAP)
        neg, s = True, s[:-1]
    s = re.sub(r"[\s$£€¥]|USD|EUR|GBP", "", s, flags=re.I)
    s = s.rstrip("%")
    if s.startswith("-"):
        neg, s = not neg, s[1:]
    if re.fullmatch(r"\d{1,3}(\.\d{3})+,\d+", s):  # 1.234,50 (European)
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    try:
        x = float(s)
    except ValueError:
        return None
    return -x if neg else x


def _try(y: int, m: int, d: int) -> Optional[dt.date]:
    try:
        return dt.date(y, m, d)
    except ValueError:
        return None


def detect_day_first(values: Iterable[Any]) -> Optional[bool]:
    """For slash/dash dates like 03/04/2026: True if the day comes first, False if the month does,
    None if the sample cannot tell (every first and second part is 12 or below)."""
    first_big = second_big = False
    for v in values:
        if not isinstance(v, str):
            continue
        m = re.fullmatch(r"\s*(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})(?:[ T].*)?\s*", v)
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        first_big |= a > 12
        second_big |= b > 12
    if first_big and not second_big:
        return True
    if second_big and not first_big:
        return False
    return None


def parse_date(v: Any, day_first: bool = False) -> Optional[dt.date]:
    if is_blank(v):
        return None
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if hasattr(v, "to_pydatetime"):  # pandas Timestamp
        try:
            return v.to_pydatetime().date()
        except (ValueError, AttributeError):
            return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        if 20000 <= v <= 80000:  # Excel serial date (1954 to 2118)
            return _EXCEL_EPOCH + dt.timedelta(days=int(v))
        if 19000101 <= v <= 21001231:  # 20260409
            s = str(int(v))
            return _try(int(s[:4]), int(s[4:6]), int(s[6:]))
        return None
    s = str(v).strip()
    m = re.fullmatch(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T].*)?", s)
    if m:
        return _try(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s)
    if m:
        return _try(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    m = re.fullmatch(r"(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{2,4})(?:[ T].*)?", s)
    if m:
        a, b, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        y = y + 2000 if y < 70 else y + 1900 if y < 100 else y
        if a > 12:
            return _try(y, b, a)
        if b > 12:
            return _try(y, a, b)
        return _try(y, b, a) if day_first else _try(y, a, b)
    m = re.fullmatch(r"(\d{1,2})[ \-/]([A-Za-z]{3})[a-z]*[ \-/,]*(\d{2,4})", s)  # 09-Apr-2026
    if m and m.group(2).lower() in _MONTHS:
        y = int(m.group(3))
        y = y + 2000 if y < 70 else y + 1900 if y < 100 else y
        return _try(y, _MONTHS[m.group(2).lower()], int(m.group(1)))
    m = re.fullmatch(r"([A-Za-z]{3})[a-z]*\.?[ ]+(\d{1,2}),?[ ]+(\d{4})", s)  # April 9, 2026
    if m and m.group(1).lower() in _MONTHS:
        return _try(int(m.group(3)), _MONTHS[m.group(1).lower()], int(m.group(2)))
    return None


def share_parsing(values: Sequence[Any], kind: str) -> float:
    """Share of the non-blank values that parse as ``kind`` ('date' or number kinds)."""
    vals = [v for v in values if not is_blank(v)]
    if not vals:
        return 0.0
    if kind == "date":
        df = detect_day_first(vals) or False
        ok = sum(parse_date(v, df) is not None for v in vals)
    else:
        ok = sum(parse_number(v) is not None for v in vals)
    return ok / len(vals)
