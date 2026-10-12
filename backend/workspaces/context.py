"""Which workspace the current request belongs to, and where its files live.

WORKSPACE_MODE=required  every request needs a workspace key; code that runs without a workspace
                         fails instead of falling back to shared data.
WORKSPACE_MODE=open      (default) the original single-workspace behaviour, so deploying this
                         changes nothing until the operator turns the new mode on.
"""
from __future__ import annotations

import contextvars
import os
import re
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

WS_ID = re.compile(r"^ws_[a-z0-9]{10}$")
LEGACY_ID = "default"
BACKEND = Path(__file__).resolve().parent.parent


class NoWorkspace(Exception):
    """Raised when code that needs a customer's workspace runs outside of one."""


@dataclass(frozen=True)
class Workspace:
    id: str
    name: str
    role: str  # admin | viewer
    legacy: bool = False
    starts_with: str = "sample"  # empty | sample
    key_label: str = ""
    key_id: str = ""

    @property
    def root(self) -> Path:
        if self.legacy:
            return Path(os.getenv("INGEST_DIR") or BACKEND / "ingest_store")
        return workspaces_dir() / self.id


def mode() -> str:
    return "required" if os.getenv("WORKSPACE_MODE", "").strip().lower() == "required" else "open"


def workspaces_dir() -> Path:
    d = Path(os.getenv("WORKSPACES_DIR") or BACKEND / "workspaces_store")
    d.mkdir(parents=True, exist_ok=True)
    return d


def legacy_workspace(role: str = "admin") -> Workspace:
    return Workspace(LEGACY_ID, "Default", role, legacy=True, starts_with="sample")


_current: contextvars.ContextVar[Optional[Workspace]] = contextvars.ContextVar("neuraflow_workspace", default=None)


def set_current(ws: Workspace) -> None:
    _current.set(ws)


def current() -> Workspace:
    ws = _current.get()
    if ws is not None:
        return ws
    if mode() == "required":
        raise NoWorkspace("This ran outside of a workspace.")
    return legacy_workspace()


@contextmanager
def use(ws: Workspace) -> Iterator[Workspace]:
    """Run a block as a workspace (background jobs, tests). The previous one is restored afterwards."""
    token = _current.set(ws)
    try:
        yield ws
    finally:
        _current.reset(token)


def data_dir() -> Path:
    ws = current()
    d = ws.root if ws.legacy else ws.root / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def models_dir() -> Path:
    ws = current()
    d = Path(os.getenv("MODEL_STORE_DIR") or BACKEND / "models_store") if ws.legacy else ws.root / "models"
    d.mkdir(parents=True, exist_ok=True)
    return d
