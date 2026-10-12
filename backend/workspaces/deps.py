"""FastAPI dependencies that decide who a request is. They are async on purpose: the workspace is set in a
ContextVar, and an async dependency runs in the request's own context, which sync endpoints inherit."""
from __future__ import annotations

import hmac
import os
import time
from typing import Dict, List, Optional

from fastapi import Header, HTTPException, Request

from . import registry
from .context import Workspace, legacy_workspace, mode, set_current

_FAILS: Dict[str, List[float]] = {}


def _ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?"))


def _throttle(request: Request) -> None:
    now = time.time()
    hits = [t for t in _FAILS.get(_ip(request), []) if now - t < 600]
    _FAILS[_ip(request)] = hits
    if len(hits) >= 20:
        raise HTTPException(429, "Too many failed sign-in attempts. Try again in a few minutes.")


def _fail(request: Request) -> None:
    _FAILS.setdefault(_ip(request), []).append(time.time())


def _token(request: Request, authorization: Optional[str], x_workspace_key: Optional[str]) -> str:
    if x_workspace_key:
        return x_workspace_key.strip()
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return ""


async def resolve(request: Request, authorization: Optional[str] = Header(None), x_workspace_key: Optional[str] = Header(None)) -> Workspace:
    """Identify the workspace for this request and make it the current one."""
    token = _token(request, authorization, x_workspace_key)
    if not token:
        if mode() == "open":
            ws = legacy_workspace()
            set_current(ws)
            return ws
        raise HTTPException(401, "Sign in with your workspace key.")
    _throttle(request)
    res = registry.authenticate(token)
    if not res.ok:
        _fail(request)
        msg = {"suspended": "This workspace is suspended. Contact your administrator.", "revoked": "This key has been revoked."}.get(res.reason, "That key was not recognised.")
        raise HTTPException(401 if res.reason != "suspended" else 403, msg)
    set_current(res.workspace)
    request.state.workspace = res.workspace
    return res.workspace


async def require_viewer(request: Request, authorization: Optional[str] = Header(None), x_workspace_key: Optional[str] = Header(None)) -> Workspace:
    return await resolve(request, authorization, x_workspace_key)


async def require_admin_ws(request: Request, authorization: Optional[str] = Header(None), x_workspace_key: Optional[str] = Header(None)) -> Workspace:
    ws = await resolve(request, authorization, x_workspace_key)
    if ws.role != "admin":
        raise HTTPException(403, "This needs an admin key.")
    return ws


def platform_enabled() -> bool:
    return bool(os.getenv("PLATFORM_ADMIN_TOKEN"))


async def require_platform(request: Request, x_platform_token: Optional[str] = Header(None)) -> None:
    """Platform operator only. Deliberately sets no workspace context."""
    expected = os.getenv("PLATFORM_ADMIN_TOKEN", "")
    if not expected:
        raise HTTPException(503, "Platform administration is off. Set PLATFORM_ADMIN_TOKEN to turn it on.")
    _throttle(request)
    if not x_platform_token or not hmac.compare_digest(x_platform_token.encode(), expected.encode()):
        _fail(request)
        raise HTTPException(401, "Platform token required.")


async def legacy_only() -> None:
    """For the original single-workspace endpoints, which read global data. Off once workspaces are required."""
    if mode() == "required":
        raise HTTPException(404, "This endpoint is not available when workspaces are required.")
