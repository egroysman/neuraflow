"""Per-customer workspaces: sign-in keys, isolation between customers, roles, and fail-closed behaviour."""
import datetime as dt
import io
import json
import os
import threading

import pytest
from cryptography.fernet import Fernet
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from ingest import service, store
from ingest.readers import SourceError
from workspaces import audit, context, deps, registry, usage

PLATFORM = {"X-Platform-Token": "plat-secret"}


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("WORKSPACES_DIR", str(tmp_path / "ws"))
    monkeypatch.setenv("INGEST_DIR", str(tmp_path / "legacy"))
    monkeypatch.setenv("WORKSPACE_MODE", "required")
    monkeypatch.setenv("PLATFORM_ADMIN_TOKEN", "plat-secret")
    monkeypatch.setenv("CONNECTION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("ALLOW_OPEN_DATA_ADMIN", raising=False)
    for k in list(os.environ):
        if k.startswith(("SFTP_", "SNOWFLAKE_", "DATABRICKS_")):
            monkeypatch.delenv(k)
    store._SNAP.clear()
    deps._FAILS.clear()
    usage._COUNTS.clear()
    registry._TOUCHED.clear()
    yield
    store._SNAP.clear()


@pytest.fixture
def client():
    from main import app

    return TestClient(app)


def H(key):
    return {"Authorization": f"Bearer {key}"}


def make(client, name="Acme", starts_with="empty"):
    r = client.post("/platform/workspaces", json={"name": name, "starts_with": starts_with}, headers=PLATFORM)
    assert r.status_code == 200, r.text
    return r.json()["workspace"]["id"], r.json()["key"]["key"]


def invoices_csv(prefix="A", n=30):
    today = dt.date.today()
    lines = ["InvoiceID,CustomerID,InvoiceDate,DueDate,InvoiceAmount,PaymentDate,TermsDays,OpenAmount,Status"]
    for i in range(n):
        d = today - dt.timedelta(days=200 - i * 5)
        due = d + dt.timedelta(days=30)
        paid = (due + dt.timedelta(days=3 + i % 4)) if i < n - 5 else None
        lines.append(f"{prefix}{i},{prefix}CUST{i % 4},{d},{due},{1000 + i * 10},{paid or ''},30,{0 if paid else 1000 + i * 10},{'Paid' if paid else 'Open'}")
    return "\n".join(lines).encode()


def load_invoices(client, key, prefix="A"):
    up = client.post("/data/upload", files={"file": ("inv.csv", io.BytesIO(invoices_csv(prefix)), "text/csv")}, headers=H(key))
    assert up.status_code == 200, up.text
    src = {"kind": "upload", "upload_id": up.json()["upload"]["id"], "object": "file"}
    a = client.post("/data/invoices/analyze", json={"source": src}, headers=H(key)).json()
    r = client.put("/data/invoices", json={"source": src, "mapping": a["mapping"]}, headers=H(key))
    assert r.status_code == 200, r.text


# ------------------------------------------------------------------ keys

def test_key_is_random_shown_once_and_stored_only_as_a_hash(client):
    ws, key = make(client)
    assert key.startswith(f"nfk.{ws}.a.")
    raw = (registry.workspaces_dir() / ws / "keys.json").read_text()
    secret = key.split(".")[-1]
    assert secret not in raw and "hash" in raw
    listed = client.get(f"/platform/workspaces/{ws}/keys", headers=PLATFORM).json()["keys"]
    assert "key" not in listed[0] and "hash" not in listed[0]


def test_malformed_wrong_and_missing_keys_are_refused(client):
    ws, key = make(client)
    secret = key.split(".")[-1]
    for bad in ["", "garbage", "nfk.x.y.z", f"nfk.{ws}.a.{'A' * 43}", f"nfk.ws_zzzzzzzzzz.a.{secret}", f"nfk.{ws}.v.{secret}"]:
        r = client.get("/auth/session", headers=H(bad) if bad else {})
        assert r.status_code == 401, bad
    assert client.get("/auth/session", headers=H(key)).status_code == 200
    assert client.get("/auth/session", headers={"X-Workspace-Key": key}).json()["workspace"]["role"] == "admin"


def test_repeated_wrong_keys_are_throttled(client):
    ws, key = make(client)
    bad = f"nfk.{ws}.a.{'A' * 43}"
    codes = [client.get("/auth/session", headers=H(bad)).status_code for _ in range(25)]
    assert 429 in codes
    assert client.get("/auth/session", headers=H(key)).status_code in (200, 429)


def test_revoking_a_key_stops_it_but_not_the_others_and_the_last_admin_is_protected(client):
    ws, k1 = make(client)
    k2 = client.post(f"/platform/workspaces/{ws}/keys", json={"role": "viewer", "label": "CFO"}, headers=PLATFORM).json()
    ids = {k["label"]: k["id"] for k in client.get(f"/platform/workspaces/{ws}/keys", headers=PLATFORM).json()["keys"]}
    assert client.delete(f"/platform/workspaces/{ws}/keys/{ids['First admin key']}", headers=PLATFORM).status_code == 400  # last admin
    client.post(f"/platform/workspaces/{ws}/keys", json={"role": "admin", "label": "Second"}, headers=PLATFORM)
    assert client.delete(f"/platform/workspaces/{ws}/keys/{ids['First admin key']}", headers=PLATFORM).status_code == 200
    r = client.get("/auth/session", headers=H(k1))
    assert r.status_code == 401 and "revoked" in r.json()["detail"]
    assert client.get("/auth/session", headers=H(k2["key"])).status_code == 200


def test_suspended_workspace_is_locked_out_until_resumed(client):
    ws, key = make(client)
    client.patch(f"/platform/workspaces/{ws}", json={"status": "suspended"}, headers=PLATFORM)
    assert client.get("/cashflow/defaults", headers=H(key)).status_code == 403
    client.patch(f"/platform/workspaces/{ws}", json={"status": "active"}, headers=PLATFORM)
    assert client.get("/cashflow/defaults", headers=H(key)).status_code == 200


def test_deleting_a_workspace_removes_its_files_and_keys(client):
    ws, key = make(client)
    load_invoices(client, key)
    root = registry.workspaces_dir() / ws
    assert root.exists()
    assert client.delete(f"/platform/workspaces/{ws}", headers=PLATFORM).status_code == 200
    assert not root.exists()
    assert client.get("/auth/session", headers=H(key)).status_code == 401


# ------------------------------------------------------------------ fail closed

PUBLIC = {("GET", "/"), ("GET", "/auth/mode"), ("GET", "/docs"), ("GET", "/redoc"), ("GET", "/openapi.json"), ("GET", "/docs/oauth2-redirect"), ("HEAD", "/docs"), ("HEAD", "/redoc"), ("HEAD", "/openapi.json"), ("HEAD", "/docs/oauth2-redirect")}


def test_every_route_refuses_anonymous_requests_in_required_mode(client):
    """New routes are protected by default: this fails if someone adds an open one."""
    from main import app

    checked = 0
    for path, ops in app.openapi()["paths"].items():
        for m in ops:
            if (m.upper(), path) in PUBLIC:
                continue
            url = path.replace("{dataset}", "invoices").replace("{cid}", "c_1").replace("{ws_id}", "ws_aaaaaaaaaa").replace("{key_id}", "k_1")
            r = client.request(m.upper(), url, json={}) if m in ("post", "put", "patch") else client.request(m.upper(), url)
            assert r.status_code in (401, 403, 404, 503), f"{m} {path} answered {r.status_code} without a key"
            checked += 1
    assert checked > 30


def test_platform_routes_need_the_platform_token_and_workspace_keys_do_not_work(client, monkeypatch):
    ws, key = make(client)
    assert client.get("/platform/workspaces").status_code == 401
    assert client.get("/platform/workspaces", headers=H(key)).status_code == 401
    assert client.get("/platform/workspaces", headers={"X-Platform-Token": "wrong"}).status_code == 401
    monkeypatch.delenv("PLATFORM_ADMIN_TOKEN")
    assert client.get("/platform/workspaces", headers=PLATFORM).status_code == 503


def test_legacy_global_endpoints_are_closed_in_required_mode(client, monkeypatch):
    ws, key = make(client)
    for m, p in [("get", "/traceability"), ("post", "/chat")]:
        assert getattr(client, m)(p, headers=H(key)).status_code in (404, 422) and getattr(client, m)(p, headers=H(key)).status_code != 200
    monkeypatch.setenv("WORKSPACE_MODE", "open")
    assert client.get("/traceability").status_code == 200


def test_code_running_outside_a_workspace_fails_instead_of_using_shared_data():
    with pytest.raises(context.NoWorkspace):
        store.get_configs()
    with pytest.raises(context.NoWorkspace):
        service.rows_for("invoices")


def test_open_mode_is_unchanged(client, monkeypatch):
    monkeypatch.setenv("WORKSPACE_MODE", "open")
    assert client.get("/cashflow/defaults").status_code == 200
    assert client.get("/data/status").json()["mode"] == "sample"
    assert client.post("/data/reset").status_code == 403  # still needs ADMIN_TOKEN
    monkeypatch.setenv("ADMIN_TOKEN", "t")
    assert client.post("/data/reset", headers={"X-Admin-Token": "t"}).status_code == 200


# ------------------------------------------------------------------ isolation

def test_one_customers_data_is_invisible_to_another(client):
    a, ka = make(client, "A")
    b, kb = make(client, "B")
    load_invoices(client, ka, "A")
    ca = client.get("/cashflow/credit", headers=H(ka)).json()
    cb = client.get("/cashflow/credit", headers=H(kb)).json()
    assert len(ca["customers"]) == 4 and all(c["customer_id"].startswith("ACUST") for c in ca["customers"])
    assert cb["customers"] == []
    assert client.get("/data/status", headers=H(kb)).json()["datasets"][0]["configured"] is False
    # B's uploads, connections, activity are its own
    assert client.get("/data/connections", headers=H(kb)).json()["connections"] == []
    assert not any(e["action"] == "dataset connected" for e in client.get("/data/activity", headers=H(kb)).json()["events"])
    assert any(e["action"] == "dataset connected" for e in client.get("/data/activity", headers=H(ka)).json()["events"])


def test_same_numbers_in_two_workspaces_do_not_share_cached_results(client):
    a, ka = make(client, "A")
    b, kb = make(client, "B")
    load_invoices(client, ka, "A")
    load_invoices(client, kb, "B")
    va = client.get("/cashflow/credit/validation", headers=H(ka)).json()
    vb = client.get("/cashflow/credit/validation", headers=H(kb)).json()
    assert va["caveat"] == vb["caveat"] and "bundled" not in va["caveat"]
    from cashflow import router as cr

    assert len({k[0] for k in cr._VALIDATION_CACHE}) >= 2  # keyed per workspace


def test_ml_results_and_models_are_per_workspace(client):
    a, ka = make(client, "A")
    b, kb = make(client, "B")
    load_invoices(client, ka, "A")
    oa = client.get("/cashflow/ml/overview", headers=H(ka)).json()
    ob = client.get("/cashflow/ml/overview", headers=H(kb)).json()
    assert oa["data"]["invoices"] == 30 and ob["data"]["invoices"] == 0
    assert "bundled" not in oa["data"]["caveat"].lower()
    assert (registry.workspaces_dir() / a / "models").exists() and not (registry.workspaces_dir() / "default").exists()


def test_concurrent_requests_see_only_their_own_workspace(client):
    a, ka = make(client, "A")
    b, kb = make(client, "B")
    load_invoices(client, ka, "A")
    load_invoices(client, kb, "B")
    errors = []

    def hammer(key, prefix):
        c = TestClient(client.app)
        for _ in range(12):
            cs = c.get("/cashflow/credit", headers=H(key)).json()["customers"]
            if not cs or not all(x["customer_id"].startswith(prefix) for x in cs):
                errors.append((prefix, cs[:1]))

    ts = [threading.Thread(target=hammer, args=a) for a in [(ka, "ACUST"), (kb, "BCUST")] * 2]
    [t.start() for t in ts]
    [t.join() for t in ts]
    assert errors == []


def test_empty_workspace_never_shows_sample_data_and_demo_workspace_does(client):
    e, ke = make(client, "Empty", "empty")
    d, kd = make(client, "Demo", "sample")
    se = client.get("/data/status", headers=H(ke)).json()
    sd = client.get("/data/status", headers=H(kd)).json()
    assert se["admin"] == {"enabled": True, "token_required": False}
    assert se["mode"] == "custom" and se["empty"] is True
    assert sd["mode"] == "sample" and sd["empty"] is False
    assert client.get("/cashflow/credit", headers=H(ke)).json()["customers"] == []
    assert len(client.get("/cashflow/credit", headers=H(kd)).json()["customers"]) > 5
    assert client.get("/cashflow/credit/validation", headers=H(kd)).json()["caveat"].startswith("This runs on the bundled sample")
    assert client.post("/cashflow/forecast", json={}, headers=H(ke)).status_code in (200, 422)


# ------------------------------------------------------------------ roles

def test_viewers_can_read_but_not_change_anything(client):
    ws, ka = make(client)
    kv = client.post(f"/platform/workspaces/{ws}/keys", json={"role": "viewer", "label": "CFO"}, headers=PLATFORM).json()["key"]
    for p in ["/cashflow/defaults", "/cashflow/credit", "/cashflow/ml/overview", "/data/status", "/auth/session"]:
        assert client.get(p, headers=H(kv)).status_code == 200, p
    assert client.get("/auth/session", headers=H(kv)).json()["workspace"]["role"] == "viewer"
    for m, p in [("get", "/data/connections"), ("get", "/data/activity"), ("post", "/data/reset"), ("post", "/cashflow/ml/retrain"),
                 ("post", "/data/connections"), ("put", "/data/ghost"), ("post", "/data/ghost/scan"), ("delete", "/data/invoices")]:
        kw = {"json": {}} if m in ("post", "put") else {}
        assert getattr(client, m)(p, headers=H(kv), **kw).status_code == 403, p
    assert client.post("/data/reset", headers=H(ka)).status_code == 200


# ------------------------------------------------------------------ credentials

def test_saved_credentials_cannot_be_decrypted_in_another_workspace(client):
    a, ka = make(client, "A")
    b, kb = make(client, "B")
    body = {"name": "Warehouse", "type": "databricks", "params": {"server_hostname": "x.cloud.databricks.com", "http_path": "/sql/1", "access_token": "dapi-secret"}}
    cid = client.post("/data/connections", json=body, headers=H(ka)).json()["id"]
    pa = registry.workspaces_dir() / a / "data" / "connections.json"
    pb = registry.workspaces_dir() / b / "data" / "connections.json"
    assert "dapi-secret" not in pa.read_text()
    pb.parent.mkdir(parents=True, exist_ok=True)
    pb.write_text(pa.read_text())  # an attacker copies the file across
    r = client.post(f"/data/connections/{cid}/test", headers=H(kb))
    assert r.status_code == 400 and "decrypt" in json.dumps(r.json()).lower()
    # and the same workspace can still read its own
    with context.use(registry.active_workspaces()[0]):
        assert store.get_connection(cid)["params"]["access_token"] == "dapi-secret"


def test_server_connections_are_not_offered_to_customers(client, monkeypatch):
    monkeypatch.setenv("SFTP_HOST", "sftp.operator.example")
    monkeypatch.setenv("SFTP_USERNAME", "ops")
    monkeypatch.setenv("SFTP_PASSWORD", "pw")
    monkeypatch.setenv("SFTP_PATTERN_INVOICES", "inv*.csv")
    ws, key = make(client)
    assert client.get("/data/connections", headers=H(key)).json()["connections"] == []
    st = client.get("/data/status", headers=H(key)).json()
    assert st["ghost"]["enabled"] is False
    r = client.post("/data/connections/env:sftp/test", headers=H(key))
    assert r.status_code == 400
    with context.use(context.legacy_workspace()):
        assert "env:sftp" in store.env_connections()


# ------------------------------------------------------------------ background jobs

def test_scheduler_refreshes_each_workspace_as_itself(client, monkeypatch):
    a, ka = make(client, "A")
    b, kb = make(client, "B")
    load_invoices(client, ka, "A")
    load_invoices(client, kb, "B")
    for key in (ka, kb):
        client.put("/data/invoices/schedule", json={"mode": "interval", "every_minutes": 15}, headers=H(key))
    # make both due
    for ws in registry.active_workspaces():
        with context.use(ws):
            cfg = store.get_configs()["invoices"]
            cfg["last_run"]["at"] -= 3600
            store.put_config("invoices", cfg)
    seen = []
    real = service.refresh_dataset
    monkeypatch.setattr(service, "refresh_dataset", lambda k, t="manual": (seen.append((context.current().id, k)), real(k, t))[1])
    service._tick({})
    assert sorted(seen) == sorted([(a, "invoices"), (b, "invoices")])
    assert client.get("/cashflow/credit", headers=H(ka)).json()["customers"][0]["customer_id"].startswith("A")


def test_a_workspaces_drop_folder_is_its_own_setting(client):
    ws, key = make(client)
    assert client.put("/data/ghost", json={"connection_id": None, "patterns": {"invoices": "inv*.csv"}}, headers=H(key)).status_code == 400
    body = {"name": "Drop", "type": "sftp", "params": {"host": "h.example", "username": "u", "password": "p", "directory": "/in"}}
    cid = client.post("/data/connections", json=body, headers=H(key)).json()["id"]
    r = client.put("/data/ghost", json={"connection_id": cid, "patterns": {"invoices": "inv*.csv"}, "schedule": "daily@05:30"}, headers=H(key))
    assert r.status_code == 200 and r.json()["ghost"]["schedule"]["at"] == "05:30"
    st = client.get("/data/status", headers=H(key)).json()["ghost"]
    assert st["enabled"] and st["source"] == "workspace" and st["patterns"] == {"invoices": "inv*.csv"}
    client.put("/data/ghost", json={"patterns": {}}, headers=H(key))
    assert client.get("/data/status", headers=H(key)).json()["ghost"]["enabled"] is False


# ------------------------------------------------------------------ limits and audit

def test_assistant_questions_are_capped_per_workspace(client, monkeypatch):
    monkeypatch.setenv("ASSISTANT_DAILY_LIMIT", "2")
    a, ka = make(client, "A")
    b, kb = make(client, "B")
    body = {"message": "hi", "forecast": {"assumptions": client.get("/cashflow/defaults", headers=H(ka)).json()["assumptions"]}}
    codes = [client.post("/cashflow/assistant", json=body, headers=H(ka)).status_code for _ in range(3)]
    assert codes[2] == 429 and 429 not in codes[:2]
    assert client.post("/cashflow/assistant", json=body, headers=H(kb)).status_code != 429


def test_activity_log_records_changes_without_secrets(client):
    ws, key = make(client)
    client.post("/data/connections", json={"name": "W", "type": "databricks", "params": {"server_hostname": "h", "http_path": "/p", "access_token": "TOPSECRET"}}, headers=H(key))
    ev = client.get("/data/activity", headers=H(key)).json()["events"]
    assert any(e["action"] == "connection saved" for e in ev)
    assert "TOPSECRET" not in json.dumps(ev)
    assert (registry.workspaces_dir() / ws / "audit.jsonl").exists()
