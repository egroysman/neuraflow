"""Workspaces and their access keys, kept on disk. Keys are random, shown once and stored only as hashes."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from .context import WS_ID, Workspace, workspaces_dir

LOCK = threading.RLock()
ROLES = ("admin", "viewer")
_TOUCHED: Dict[str, float] = {}


class WorkspaceError(Exception):
    """A problem the operator can act on. Safe to show."""


def _read(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text()) if path.exists() else default
    except (OSError, ValueError):
        return default


def _write(path: Path, data: Any) -> None:
    tmp = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1))
    os.replace(tmp, path)


def _index() -> Dict[str, Any]:
    return _read(workspaces_dir() / "workspaces.json", {})


def _put_index(idx: Dict[str, Any]) -> None:
    _write(workspaces_dir() / "workspaces.json", idx)


def _keys_path(ws_id: str) -> Path:
    if not WS_ID.match(ws_id):
        raise WorkspaceError("Unknown workspace.")
    return workspaces_dir() / ws_id / "keys.json"


def _hash(ws_id: str, secret: str) -> str:
    return hashlib.sha256(f"{ws_id}:{secret}".encode()).hexdigest()


def make_token(ws_id: str, role: str, secret: str) -> str:
    return f"nfk.{ws_id}.{role[0]}.{secret}"


def parse_token(token: str) -> Optional[tuple]:
    parts = (token or "").strip().split(".")
    if len(parts) != 4 or parts[0] != "nfk" or not WS_ID.match(parts[1]) or parts[2] not in ("a", "v") or not re.fullmatch(r"[A-Za-z0-9_-]{43}", parts[3]):
        return None
    return parts[1], parts[2], parts[3]


# ------------------------------------------------------------------ workspaces

def create_workspace(name: str, starts_with: str = "empty") -> Dict[str, Any]:
    name = (name or "").strip()[:80]
    if not name:
        raise WorkspaceError("Give the workspace a name.")
    if starts_with not in ("empty", "sample"):
        raise WorkspaceError("A workspace starts empty or with the sample data.")
    with LOCK:
        idx = _index()
        ws_id = "ws_" + "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(10))
        while ws_id in idx:
            ws_id = "ws_" + "".join(secrets.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(10))
        (workspaces_dir() / ws_id).mkdir(parents=True)
        idx[ws_id] = {"id": ws_id, "name": name, "starts_with": starts_with, "status": "active", "created_at": time.time()}
        _put_index(idx)
        key = issue_key(ws_id, "admin", "First admin key")
    return {"workspace": idx[ws_id], "key": key}


def get_meta(ws_id: str) -> Optional[Dict[str, Any]]:
    return _index().get(ws_id) if WS_ID.match(ws_id or "") else None


def list_workspaces() -> List[Dict[str, Any]]:
    out = []
    for meta in sorted(_index().values(), key=lambda m: m["created_at"]):
        keys = _read(_keys_path(meta["id"]), {})
        live = [k for k in keys.values() if not k["revoked"]]
        used = [k["last_used_at"] for k in live if k.get("last_used_at")]
        out.append({**meta, "keys": len(live), "last_active": max(used) if used else None, "datasets": _dataset_count(meta["id"])})
    return out


def _dataset_count(ws_id: str) -> int:
    return len(_read(workspaces_dir() / ws_id / "data" / "datasets.json", {}))


def set_status(ws_id: str, status: str) -> None:
    if status not in ("active", "suspended"):
        raise WorkspaceError("Status must be active or suspended.")
    with LOCK:
        idx = _index()
        if ws_id not in idx:
            raise WorkspaceError("Unknown workspace.")
        idx[ws_id]["status"] = status
        _put_index(idx)


def rename(ws_id: str, name: str) -> None:
    with LOCK:
        idx = _index()
        if ws_id not in idx:
            raise WorkspaceError("Unknown workspace.")
        idx[ws_id]["name"] = (name or "").strip()[:80] or idx[ws_id]["name"]
        _put_index(idx)


def delete_workspace(ws_id: str) -> None:
    """Remove the workspace, its keys, uploads, saved connections, loaded data and models. Cannot be undone."""
    with LOCK:
        idx = _index()
        if ws_id not in idx:
            raise WorkspaceError("Unknown workspace.")
        root = (workspaces_dir() / ws_id).resolve()
        if root.parent != workspaces_dir().resolve():
            raise WorkspaceError("Unknown workspace.")
        del idx[ws_id]
        _put_index(idx)
        shutil.rmtree(root, ignore_errors=True)
    for hook in _ON_DELETE:
        hook(ws_id)


_ON_DELETE: List[Any] = []


def on_delete(fn) -> None:
    _ON_DELETE.append(fn)


# ------------------------------------------------------------------ keys

def issue_key(ws_id: str, role: str, label: str = "") -> Dict[str, Any]:
    """Create a key. The returned ``key`` is the only time its value is available."""
    if role not in ROLES:
        raise WorkspaceError("A key is either admin or viewer.")
    with LOCK:
        if ws_id not in _index():
            raise WorkspaceError("Unknown workspace.")
        path = _keys_path(ws_id)
        keys = _read(path, {})
        if sum(1 for k in keys.values() if not k["revoked"]) >= 50:
            raise WorkspaceError("This workspace already has 50 active keys. Revoke some first.")
        secret = secrets.token_urlsafe(32)
        key_id = "k_" + secrets.token_hex(4)
        keys[key_id] = {"id": key_id, "role": role, "label": (label or "").strip()[:60], "hash": _hash(ws_id, secret),
                        "created_at": time.time(), "last_used_at": None, "revoked": False}
        _write(path, keys)
    return {"id": key_id, "role": role, "label": keys[key_id]["label"], "key": make_token(ws_id, role, secret)}


def list_keys(ws_id: str) -> List[Dict[str, Any]]:
    keys = _read(_keys_path(ws_id), {})
    return [{k: v for k, v in rec.items() if k != "hash"} for rec in sorted(keys.values(), key=lambda r: r["created_at"])]


def revoke_key(ws_id: str, key_id: str) -> None:
    with LOCK:
        path = _keys_path(ws_id)
        keys = _read(path, {})
        if key_id not in keys:
            raise WorkspaceError("Unknown key.")
        if keys[key_id]["role"] == "admin" and keys[key_id]["revoked"] is False and sum(1 for k in keys.values() if k["role"] == "admin" and not k["revoked"]) == 1:
            raise WorkspaceError("This is the last admin key. Issue another admin key first so the customer is not locked out.")
        keys[key_id]["revoked"] = True
        _write(path, keys)
        _TOUCHED.pop(f"{ws_id}:{key_id}", None)


# ------------------------------------------------------------------ sign-in

@dataclass
class AuthResult:
    ok: bool
    workspace: Optional[Workspace] = None
    reason: str = ""


def authenticate(token: str) -> AuthResult:
    parsed = parse_token(token)
    if not parsed:
        return AuthResult(False, reason="malformed")
    ws_id, role_char, secret = parsed
    meta = get_meta(ws_id)
    if not meta:
        return AuthResult(False, reason="unknown")
    want = _hash(ws_id, secret)
    found = None
    for rec in _read(_keys_path(ws_id), {}).values():
        if hmac.compare_digest(rec["hash"], want):  # compare against every key: no early exit on a match
            found = rec
    if found is None or found["role"][0] != role_char:
        return AuthResult(False, reason="unknown")
    if found["revoked"]:
        return AuthResult(False, reason="revoked")
    if meta["status"] != "active":
        return AuthResult(False, reason="suspended")
    _touch(ws_id, found["id"])
    return AuthResult(True, Workspace(ws_id, meta["name"], found["role"], legacy=False, starts_with=meta["starts_with"], key_label=found["label"], key_id=found["id"]))


def _touch(ws_id: str, key_id: str) -> None:
    """Record last use, at most once a minute per key, so reading a page does not write to disk."""
    now = time.time()
    k = f"{ws_id}:{key_id}"
    if now - _TOUCHED.get(k, 0) < 60:
        return
    _TOUCHED[k] = now
    with LOCK:
        path = _keys_path(ws_id)
        keys = _read(path, {})
        if key_id in keys:
            keys[key_id]["last_used_at"] = now
            _write(path, keys)


def active_workspaces() -> List[Workspace]:
    """For background jobs: every active workspace, acting as admin."""
    return [Workspace(m["id"], m["name"], "admin", legacy=False, starts_with=m["starts_with"]) for m in _index().values() if m["status"] == "active"]
