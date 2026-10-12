"""Data page API. Everything except /data/status needs the admin token."""
from __future__ import annotations

import hmac
import os
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel

from . import diagnose, guide, readers, service, store
from .readers import SourceError
from .schemas import DATASETS
from workspaces import audit
from workspaces.context import mode
from workspaces.deps import require_viewer

router = APIRouter(prefix="/data", tags=["data"])
_fails: Dict[str, List[float]] = defaultdict(list)


async def require_admin(request: Request, x_admin_token: Optional[str] = Header(default=None),
                        authorization: Optional[str] = Header(default=None), x_workspace_key: Optional[str] = Header(default=None)) -> None:
    """A workspace admin key changes that workspace's data. Without a key, only the original single-workspace
    mode applies, and it keeps using ADMIN_TOKEN."""
    from workspaces import deps

    if x_workspace_key or (authorization and authorization.lower().startswith("bearer ")):
        await deps.require_admin_ws(request, authorization, x_workspace_key)
        return
    if mode() == "required":
        raise HTTPException(401, "Sign in with your workspace key.")
    token = os.getenv("ADMIN_TOKEN", "")
    if not token:
        if service.admin_enabled():
            return
        raise HTTPException(403, "Changing data is turned off. Set ADMIN_TOKEN on the server to turn it on.")
    ip = (request.client.host if request.client else "?")
    now = time.time()
    _fails[ip] = [t for t in _fails[ip] if now - t < 600]
    if len(_fails[ip]) >= 10:
        raise HTTPException(429, "Too many wrong tokens. Try again in a few minutes.")
    if not x_admin_token or not hmac.compare_digest(x_admin_token.encode(), token.encode()):
        _fails[ip].append(now)
        raise HTTPException(401, "Enter the admin token to change data.")


def _err(e: SourceError) -> HTTPException:
    msg = str(e)
    hint = diagnose.diagnose(msg) if msg.startswith("The database said:") else None
    if hint:
        return HTTPException(400, {"code": hint["code"], "message": msg, "hint": hint})
    if msg.startswith("ENCRYPTION_KEY_MISSING:"):
        return HTTPException(400, {"code": "ENCRYPTION_KEY_MISSING", "message": msg.split(":", 1)[1].strip()})
    if msg.startswith("HOSTKEY:"):
        return HTTPException(400, {"code": "HOST_KEY_UNPINNED", "message": "This server's identity has not been confirmed yet.", "host_key_sha256": msg[8:]})
    return HTTPException(400, msg)


def _run(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except SourceError as e:
        raise _err(e)


def _ds(key: str) -> str:
    if key not in DATASETS:
        raise HTTPException(404, "Unknown dataset.")
    return key


class SourceBody(BaseModel):
    kind: str
    upload_id: Optional[str] = None
    connection_id: Optional[str] = None
    object: Optional[str] = None
    sheet: Optional[str] = None
    header_row: Optional[int] = None


class AnalyzeBody(BaseModel):
    source: SourceBody
    mapping: Optional[Dict[str, Optional[str]]] = None
    options: Optional[Dict[str, Any]] = None


class SaveBody(AnalyzeBody):
    mapping: Dict[str, Optional[str]]
    schedule: Optional[Dict[str, Any]] = None


class ConnBody(BaseModel):
    name: str
    type: str
    params: Dict[str, Any]


@router.get("/status", dependencies=[Depends(require_viewer)])
def get_status():
    return service.status()


@router.get("/connections", dependencies=[Depends(require_admin)])
def connections():
    return {"connections": store.list_connections(), "encryption_ready": store.encryption_ready()}


@router.post("/connections", dependencies=[Depends(require_admin)])
def create_connection(b: ConnBody):
    audit.log("connection saved", f"{b.type}: {b.name}")
    return _run(store.save_connection, b.name, b.type, b.params)


@router.put("/connections/{cid}", dependencies=[Depends(require_admin)])
def update_connection(cid: str, b: ConnBody):
    audit.log("connection updated", cid)
    if cid.startswith("env:"):
        raise HTTPException(400, "Server-setting connections are changed on the server.")
    return _run(store.save_connection, b.name, b.type, b.params, cid)


@router.delete("/connections/{cid}", dependencies=[Depends(require_admin)])
def remove_connection(cid: str):
    audit.log("connection deleted", cid)
    if cid.startswith("env:"):
        raise HTTPException(400, "Server-setting connections are changed on the server.")
    _run(store.delete_connection, cid)
    return {"ok": True}


@router.post("/connections/{cid}/test", dependencies=[Depends(require_admin)])
def test_connection(cid: str):
    return _run(service.test_connection, cid)


@router.post("/connections/host-key", dependencies=[Depends(require_admin)])
def host_key(b: ConnBody):
    if b.type != "sftp":
        raise HTTPException(400, "Host keys apply to SFTP only.")
    return {"host_key_sha256": _run(service.observe_host_key, b.params)}


class GuideBody(BaseModel):
    type: str
    params: Dict[str, Any] = {}


@router.post("/setup-guide", dependencies=[Depends(require_admin)])
def setup_guide(b: GuideBody):
    out = _run(guide.build, b.type, b.params)
    out["egress_ips"] = guide.egress_ips()
    return out


@router.post("/upload", dependencies=[Depends(require_admin)])
async def upload(file: UploadFile = File(...)):
    audit.log("file uploaded", file.filename or "")
    raw = await file.read(readers.MAX_UPLOAD_BYTES + 1)
    if len(raw) > readers.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"The file is larger than {readers.MAX_UPLOAD_BYTES // (1024 * 1024)} MB.")
    if not raw:
        raise HTTPException(400, "The file is empty.")
    meta = _run(store.save_upload, file.filename or "upload", raw)
    return {"upload": {k: meta[k] for k in ("id", "filename", "size")}, "objects": _run(readers.file_objects, raw, meta["filename"])}


@router.post("/objects", dependencies=[Depends(require_admin)])
def objects(b: SourceBody):
    return {"objects": _run(service.list_objects, b.model_dump())}


class GhostBody(BaseModel):
    connection_id: Optional[str] = None
    patterns: Dict[str, str] = {}
    schedule: Optional[Any] = None


@router.put("/ghost", dependencies=[Depends(require_admin)])
def set_ghost(b: GhostBody):
    audit.log("drop folder changed")
    return {"ghost": _run(service.set_ghost_config, b.connection_id, b.patterns, b.schedule)}


@router.post("/{dataset}/analyze", dependencies=[Depends(require_admin)])
def analyze(dataset: str, b: AnalyzeBody):
    return _run(service.analyze, _ds(dataset), b.source.model_dump(), b.mapping, b.options)


@router.put("/{dataset}", dependencies=[Depends(require_admin)])
def save(dataset: str, b: SaveBody):
    audit.log("dataset connected", dataset)
    return _run(service.save_dataset, _ds(dataset), b.source.model_dump(), b.mapping, b.options, b.schedule)


@router.post("/{dataset}/refresh", dependencies=[Depends(require_admin)])
def refresh(dataset: str):
    audit.log("dataset refreshed", dataset)
    return _run(service.refresh_dataset, _ds(dataset), "manual")


@router.put("/{dataset}/schedule", dependencies=[Depends(require_admin)])
def schedule(dataset: str, b: Dict[str, Any]):
    audit.log("schedule changed", dataset)
    return _run(service.set_schedule, _ds(dataset), b)


@router.delete("/{dataset}", dependencies=[Depends(require_admin)])
def reset_one(dataset: str):
    audit.log("dataset removed", dataset)
    service.reset_dataset(_ds(dataset))
    return {"ok": True}


@router.post("/reset", dependencies=[Depends(require_admin)])
def reset_everything():
    audit.log("all data removed")
    service.reset_all()
    return {"ok": True, "mode": service.status()["mode"]}


@router.post("/ghost/scan", dependencies=[Depends(require_admin)])
def ghost_scan():
    return {"state": service.ghost_scan(retry_after=0)}


@router.get("/activity", dependencies=[Depends(require_admin)])
def activity():
    return {"events": audit.recent(20)}
