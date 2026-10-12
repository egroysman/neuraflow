"""Platform administration (create and manage workspaces) and the sign-in check."""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from . import audit, context, deps, registry
from .registry import WorkspaceError

platform = APIRouter(prefix="/platform", tags=["platform"], dependencies=[Depends(deps.require_platform)])
auth = APIRouter(prefix="/auth", tags=["auth"])


def _run(fn, *a, **kw):
    try:
        return fn(*a, **kw)
    except WorkspaceError as e:
        raise HTTPException(400, str(e))


class NewWorkspace(BaseModel):
    name: str
    starts_with: str = "empty"


class NewKey(BaseModel):
    role: str = "admin"
    label: str = ""


class Patch(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None


@platform.get("/workspaces")
def list_workspaces():
    return {"workspaces": registry.list_workspaces()}


@platform.post("/workspaces")
def create(b: NewWorkspace):
    out = _run(registry.create_workspace, b.name, b.starts_with)
    audit.log("workspace created", b.starts_with, ws_id=out["workspace"]["id"], actor="platform")
    return out


@platform.patch("/workspaces/{ws_id}")
def patch(ws_id: str, b: Patch):
    if b.name is not None:
        _run(registry.rename, ws_id, b.name)
    if b.status is not None:
        _run(registry.set_status, ws_id, b.status)
        audit.log(f"workspace {b.status}", ws_id=ws_id, actor="platform")
    return {"workspace": registry.get_meta(ws_id)}


@platform.delete("/workspaces/{ws_id}")
def delete(ws_id: str):
    _run(registry.delete_workspace, ws_id)
    return {"ok": True}


@platform.get("/workspaces/{ws_id}/keys")
def keys(ws_id: str):
    if not registry.get_meta(ws_id):
        raise HTTPException(404, "Unknown workspace.")
    return {"keys": registry.list_keys(ws_id)}


@platform.post("/workspaces/{ws_id}/keys")
def issue(ws_id: str, b: NewKey):
    out = _run(registry.issue_key, ws_id, b.role, b.label)
    audit.log(f"{b.role} key issued", b.label, ws_id=ws_id, actor="platform")
    return out


@platform.delete("/workspaces/{ws_id}/keys/{key_id}")
def revoke(ws_id: str, key_id: str):
    _run(registry.revoke_key, ws_id, key_id)
    audit.log("key revoked", key_id, ws_id=ws_id, actor="platform")
    return {"ok": True}


@auth.get("/mode")
def get_mode():
    """Public: tells the app whether it must ask for a key."""
    return {"mode": context.mode(), "login_required": deps.login_required(), "platform_admin": deps.platform_enabled()}


@auth.get("/session")
async def session(ws: context.Workspace = Depends(deps.require_viewer)):
    return {"workspace": {"id": ws.id, "name": ws.name, "role": ws.role, "legacy": ws.legacy, "starts_with": ws.starts_with}}


# ------------------------------------------------------------------ demo requests from the public site

def _leads():
    import json

    p = context.workspaces_dir() / "leads.json"
    try:
        return json.loads(p.read_text()) if p.exists() else []
    except (OSError, ValueError):
        return []


def _save_leads(leads) -> None:
    import json
    import os

    p = context.workspaces_dir() / "leads.json"
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(leads, indent=1))
    os.replace(tmp, p)


class LeadPatch(BaseModel):
    handled: bool


@platform.get("/leads")
def list_leads():
    return {"leads": list(reversed(_leads()))}


@platform.patch("/leads/{lead_id}")
def patch_lead(lead_id: str, b: LeadPatch):
    from public.router import _LOCK

    with _LOCK:
        leads = _leads()
        for l in leads:
            if l["id"] == lead_id:
                l["handled"] = b.handled
                _save_leads(leads)
                return {"ok": True}
    raise HTTPException(404, "Unknown request.")


@platform.delete("/leads/{lead_id}")
def delete_lead(lead_id: str):
    from public.router import _LOCK

    with _LOCK:
        leads = _leads()
        kept = [l for l in leads if l["id"] != lead_id]
        if len(kept) == len(leads):
            raise HTTPException(404, "Unknown request.")
        _save_leads(kept)
    return {"ok": True}
