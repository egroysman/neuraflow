"""A daily cap on assistant questions per workspace, so one customer cannot run up the AI bill."""
from __future__ import annotations

import datetime as dt
import os
import threading
from typing import Dict, Tuple

from fastapi import HTTPException

from . import context

_LOCK = threading.Lock()
_COUNTS: Dict[Tuple[str, str], int] = {}


def limit() -> int:
    try:
        return int(os.getenv("ASSISTANT_DAILY_LIMIT", "200"))
    except ValueError:
        return 200


def charge_assistant() -> None:
    ws = context.current()
    if ws.legacy:
        return  # the original single-workspace mode is unchanged
    today = dt.date.today().isoformat()
    with _LOCK:
        for k in [k for k in _COUNTS if k[1] != today]:
            _COUNTS.pop(k, None)
        n = _COUNTS.get((ws.id, today), 0)
        if n >= limit():
            raise HTTPException(429, f"This workspace has used its {limit()} assistant questions for today. It resets tomorrow.")
        _COUNTS[(ws.id, today)] = n + 1
