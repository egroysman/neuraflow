"""A short record of who changed what in a workspace. Never stores secrets or data values."""
from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import context

_LOCK = threading.Lock()
MAX_BYTES = 512 * 1024


def _path(ws_id: Optional[str] = None) -> Path:
    if ws_id:
        d = context.workspaces_dir() / ws_id
        d.mkdir(parents=True, exist_ok=True)
        return d / "audit.jsonl"
    return context.data_dir() / "audit.jsonl"


def log(action: str, detail: str = "", ws_id: Optional[str] = None, actor: str = "") -> None:
    try:
        if not actor and not ws_id:
            ws = context.current()
            actor = ws.key_label or ws.key_id or ("operator" if ws.legacy else "")
        p = _path(ws_id)
        with _LOCK:
            if p.exists() and p.stat().st_size > MAX_BYTES:  # keep the newest half
                lines = p.read_text().splitlines()
                p.write_text("\n".join(lines[len(lines) // 2:]) + "\n")
            with p.open("a") as fh:
                fh.write(json.dumps({"at": time.time(), "actor": actor, "action": action, "detail": detail[:200]}) + "\n")
    except Exception:  # noqa: BLE001 - an audit failure must not break the action
        pass


def recent(n: int = 20) -> List[Dict[str, Any]]:
    p = _path()
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines()[-n:]:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return list(reversed(out))
