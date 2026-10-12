"""Where uploads, saved connections, dataset settings and loaded snapshots live on disk.

Secrets (passwords, tokens, private keys) are encrypted with CONNECTION_ENCRYPTION_KEY and are
never returned by the API. Everything else is plain JSON. On a host with a temporary disk,
mount a volume and point INGEST_DIR at it, otherwise this resets on each deploy.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import secrets
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .readers import SourceError

SECRET_FIELDS = {
    "snowflake": ("password", "private_key", "private_key_passphrase"),
    "databricks": ("access_token",),
    "sftp": ("password", "private_key", "private_key_passphrase"),
}
PUBLIC_FIELDS = {
    "snowflake": ("account", "user", "warehouse", "database", "schema", "role"),
    "databricks": ("server_hostname", "http_path", "catalog", "schema"),
    "sftp": ("host", "port", "username", "directory", "host_key_sha256", "trust_any_host_key"),
}
LOCK = threading.RLock()


def base_dir() -> Path:
    """The current workspace's data folder. Raises if there is no workspace (required mode)."""
    from workspaces import context

    return context.data_dir()


def _read_json(name: str, default: Any) -> Any:
    p = base_dir() / name
    try:
        return json.loads(p.read_text()) if p.exists() else default
    except (OSError, ValueError):
        return default


def _write_json(name: str, data: Any) -> None:
    p = base_dir() / name
    tmp = p.with_suffix(p.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data, indent=1, default=str))
    os.replace(tmp, p)


# ------------------------------------------------------------------ encryption

def _fernet():
    key = os.getenv("CONNECTION_ENCRYPTION_KEY", "").strip()
    if not key:
        raise SourceError("ENCRYPTION_KEY_MISSING: Saving a connection needs CONNECTION_ENCRYPTION_KEY on the server. Generate one with: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\"")
    import base64

    from cryptography.fernet import Fernet
    from workspaces import context

    try:
        Fernet(key.encode())  # validates the master key
    except Exception:  # noqa: BLE001
        raise SourceError("CONNECTION_ENCRYPTION_KEY is not a valid key. Generate one with Fernet.generate_key().")
    ws = context.current()
    if ws.legacy:
        return Fernet(key.encode())
    # Each workspace gets its own key derived from the master, so one workspace's saved
    # credentials cannot be read by copying them into another.
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    derived = HKDF(algorithm=hashes.SHA256(), length=32, salt=None, info=f"neuraflow-ws:{ws.id}".encode()).derive(base64.urlsafe_b64decode(key.encode()))
    return Fernet(base64.urlsafe_b64encode(derived))


def encryption_ready() -> bool:
    try:
        _fernet()
        return True
    except SourceError:
        return False


def encrypt_secrets(d: Dict[str, str]) -> str:
    return _fernet().encrypt(json.dumps(d).encode()).decode()


def decrypt_secrets(token: str) -> Dict[str, str]:
    from cryptography.fernet import InvalidToken

    try:
        return json.loads(_fernet().decrypt(token.encode()))
    except InvalidToken:
        raise SourceError("The saved credentials cannot be decrypted. CONNECTION_ENCRYPTION_KEY has changed; re-enter them.")


# ------------------------------------------------------------------ env connections

def env_connections() -> Dict[str, Dict[str, Any]]:
    """Connections defined by server settings. Read-only, never stored, never shown.
    Only the legacy workspace sees them: they are the operator's own accounts, not a customer's."""
    from workspaces import context

    if not context.current().legacy:
        return {}
    e = os.getenv
    out: Dict[str, Dict[str, Any]] = {}
    if e("SNOWFLAKE_ACCOUNT") and e("SNOWFLAKE_USER") and (e("SNOWFLAKE_PASSWORD") or e("SNOWFLAKE_PRIVATE_KEY")):
        out["env:snowflake"] = {"id": "env:snowflake", "name": "Snowflake (server settings)", "type": "snowflake", "env": True,
                                "params": {"account": e("SNOWFLAKE_ACCOUNT"), "user": e("SNOWFLAKE_USER"), "password": e("SNOWFLAKE_PASSWORD"),
                                           "private_key": e("SNOWFLAKE_PRIVATE_KEY"), "private_key_passphrase": e("SNOWFLAKE_PRIVATE_KEY_PASSPHRASE"),
                                           "warehouse": e("SNOWFLAKE_WAREHOUSE"), "database": e("SNOWFLAKE_DATABASE"), "schema": e("SNOWFLAKE_SCHEMA"), "role": e("SNOWFLAKE_ROLE")}}
    if e("DATABRICKS_SERVER_HOSTNAME") and e("DATABRICKS_HTTP_PATH") and e("DATABRICKS_TOKEN"):
        out["env:databricks"] = {"id": "env:databricks", "name": "Databricks (server settings)", "type": "databricks", "env": True,
                                 "params": {"server_hostname": e("DATABRICKS_SERVER_HOSTNAME"), "http_path": e("DATABRICKS_HTTP_PATH"),
                                            "access_token": e("DATABRICKS_TOKEN"), "catalog": e("DATABRICKS_CATALOG"), "schema": e("DATABRICKS_SCHEMA")}}
    if e("SFTP_HOST") and e("SFTP_USERNAME") and (e("SFTP_PASSWORD") or e("SFTP_PRIVATE_KEY")):
        out["env:sftp"] = {"id": "env:sftp", "name": "SFTP (server settings)", "type": "sftp", "env": True,
                           "params": {"host": e("SFTP_HOST"), "port": e("SFTP_PORT") or 22, "username": e("SFTP_USERNAME"), "password": e("SFTP_PASSWORD"),
                                      "private_key": e("SFTP_PRIVATE_KEY"), "private_key_passphrase": e("SFTP_PRIVATE_KEY_PASSPHRASE"),
                                      "directory": e("SFTP_DIRECTORY") or ".", "host_key_sha256": e("SFTP_HOST_KEY_SHA256")}}
    return out


# ------------------------------------------------------------------ saved connections

def _public(c: Dict[str, Any]) -> Dict[str, Any]:
    p = c.get("params") or {}
    secret_names = SECRET_FIELDS.get(c["type"], ())
    return {"id": c["id"], "name": c["name"], "type": c["type"], "env": bool(c.get("env")),
            "params": {k: p.get(k) for k in PUBLIC_FIELDS[c["type"]] if p.get(k) not in (None, "")},
            "secrets_set": [k for k in secret_names if p.get(k)]}


def list_connections() -> List[Dict[str, Any]]:
    out = [_public(c) for c in env_connections().values()]
    with LOCK:
        for c in _read_json("connections.json", {}).values():
            out.append({"id": c["id"], "name": c["name"], "type": c["type"], "env": False,
                        "params": {k: v for k, v in c["public"].items() if v not in (None, "")},
                        "secrets_set": list(c.get("secret_names", []))})
    return out


def get_connection(cid: str) -> Dict[str, Any]:
    """Full connection with secrets, for server-side use only."""
    env = env_connections()
    if cid in env:
        return env[cid]
    with LOCK:
        c = _read_json("connections.json", {}).get(cid)
    if not c:
        raise SourceError("That connection no longer exists.")
    params = dict(c["public"])
    if c.get("secret"):
        params.update(decrypt_secrets(c["secret"]))
    return {"id": c["id"], "name": c["name"], "type": c["type"], "env": False, "params": params}


def save_connection(name: str, ctype: str, params: Dict[str, Any], cid: Optional[str] = None) -> Dict[str, Any]:
    if ctype not in SECRET_FIELDS:
        raise SourceError("Connection type must be snowflake, databricks or sftp.")
    name = (name or "").strip()[:80]
    if not name:
        raise SourceError("Give the connection a name.")
    with LOCK:
        store = _read_json("connections.json", {})
        old = store.get(cid) if cid else None
        if cid and not old:
            raise SourceError("That connection no longer exists.")
        public = {k: (str(params.get(k)).strip() if params.get(k) not in (None, "") else None) for k in PUBLIC_FIELDS[ctype]}
        if ctype == "sftp":
            public["trust_any_host_key"] = bool(params.get("trust_any_host_key"))
        secrets_in = {k: params[k] for k in SECRET_FIELDS[ctype] if params.get(k)}
        kept: Dict[str, str] = {}
        if old and old.get("secret"):
            kept = decrypt_secrets(old["secret"])
        merged = {**kept, **secrets_in}
        if not merged:
            raise SourceError("Enter the password, token or key for this connection.")
        token = encrypt_secrets(merged)
        cid = cid or "c_" + secrets.token_hex(5)
        store[cid] = {"id": cid, "name": name, "type": ctype, "public": public, "secret": token, "secret_names": sorted(merged)}
        _write_json("connections.json", store)
    return {"id": cid, "name": name, "type": ctype}


def delete_connection(cid: str) -> None:
    with LOCK:
        store = _read_json("connections.json", {})
        if cid not in store:
            raise SourceError("That connection no longer exists.")
        in_use = [k for k, v in _read_json("datasets.json", {}).items() if v.get("source", {}).get("connection_id") == cid]
        if in_use:
            raise SourceError("This connection is used by: " + ", ".join(in_use) + ". Switch those first.")
        del store[cid]
        _write_json("connections.json", store)


# ------------------------------------------------------------------ uploads

def save_upload(filename: str, raw: bytes) -> Dict[str, Any]:
    safe = re.sub(r"[^A-Za-z0-9._ -]", "_", os.path.basename(filename or "upload"))[:120] or "upload"
    uid = "u_" + secrets.token_hex(6)
    d = base_dir() / "uploads"
    d.mkdir(exist_ok=True)
    with LOCK:
        (d / uid).write_bytes(raw)
        meta = _read_json("uploads.json", {})
        meta[uid] = {"id": uid, "filename": safe, "size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()[:16], "uploaded_at": time.time()}
        _write_json("uploads.json", meta)
    return meta[uid]


def get_upload(uid: str) -> Dict[str, Any]:
    meta = _read_json("uploads.json", {}).get(uid)
    p = base_dir() / "uploads" / re.sub(r"[^a-z0-9_]", "", uid)
    if not meta or not p.exists():
        raise SourceError("That uploaded file is no longer on the server. Upload it again.")
    return {**meta, "bytes": p.read_bytes()}


# ------------------------------------------------------------------ dataset settings and snapshots

def get_configs() -> Dict[str, Any]:
    return _read_json("datasets.json", {})


def put_config(key: str, cfg: Optional[Dict[str, Any]]) -> None:
    with LOCK:
        all_ = _read_json("datasets.json", {})
        if cfg is None:
            all_.pop(key, None)
        else:
            all_[key] = cfg
        _write_json("datasets.json", all_)


_SNAP: Dict[str, Any] = {}


def write_snapshot(key: str, rows: List[Dict[str, Any]]) -> None:
    d = base_dir() / "snapshots"
    d.mkdir(exist_ok=True)
    p = d / f"{key}.json.gz"
    tmp = p.with_suffix(".tmp")
    with gzip.open(tmp, "wt", encoding="utf-8") as fh:
        json.dump(rows, fh)
    os.replace(tmp, p)
    _SNAP.pop((str(base_dir()), key), None)


def read_snapshot(key: str) -> Optional[List[Dict[str, Any]]]:
    p = base_dir() / "snapshots" / f"{key}.json.gz"
    if not p.exists():
        return None
    m = p.stat().st_mtime_ns
    hit = _SNAP.get((str(base_dir()), key))
    if hit and hit[0] == m:
        return hit[1]
    with gzip.open(p, "rt", encoding="utf-8") as fh:
        rows = json.load(fh)
    _SNAP[(str(base_dir()), key)] = (m, rows)
    return rows


def delete_snapshot(key: str) -> None:
    p = base_dir() / "snapshots" / f"{key}.json.gz"
    if p.exists():
        p.unlink()
    _SNAP.pop((str(base_dir()), key), None)
