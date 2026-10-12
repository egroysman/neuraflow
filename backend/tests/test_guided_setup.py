"""Guided warehouse setup: generated grants, error explanations, and the connection check."""
import re

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ingest import diagnose, guide, service, store
from ingest.readers import SourceError
from ingest.router import router as ingest_router


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("INGEST_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("ALLOW_OPEN_DATA_ADMIN", "1")
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.delenv("NEURAFLOW_EGRESS_IPS", raising=False)
    monkeypatch.setenv("CONNECTION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    store._SNAP.clear()


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(ingest_router)
    return TestClient(app)


def sql_of(g):
    return "\n".join(s.get("sql", "") for s in g["steps"])


# ------------------------------------------------------------------ generated scripts

def test_snowflake_script_grants_read_only_and_nothing_else():
    g = guide.build("snowflake", {"database": "FINANCE", "schemas": "ERP, GL"})
    sql = sql_of(g)
    assert "GRANT USAGE ON DATABASE FINANCE TO ROLE NEURAFLOW_READER" in sql
    assert "GRANT SELECT ON ALL TABLES IN SCHEMA FINANCE.ERP" in sql and "GRANT SELECT ON FUTURE VIEWS IN SCHEMA FINANCE.GL" in sql
    assert "XSMALL" in sql and "AUTO_SUSPEND = 60" in sql
    grants = [l for l in sql.splitlines() if l.startswith("GRANT")]
    assert grants and all(re.match(r"GRANT (USAGE|SELECT) ON ", l) or l.startswith("GRANT ROLE") for l in grants), grants
    assert not re.search(r"OWNERSHIP|ALL PRIVILEGES|ACCOUNTADMIN|MODIFY|INSERT|DELETE|DROP", sql.upper())
    assert g["fill"] == {"user": "NEURAFLOW_SVC", "warehouse": "NEURAFLOW_WH", "database": "FINANCE", "role": "NEURAFLOW_READER"}


def test_snowflake_key_and_password_variants():
    key = sql_of(guide.build("snowflake", {"database": "D", "auth": "key"}))
    pw = sql_of(guide.build("snowflake", {"database": "D", "auth": "password"}))
    assert "RSA_PUBLIC_KEY" in key and "PASSWORD" not in key
    assert "PASSWORD = '<choose" in pw and "RSA_PUBLIC_KEY" not in pw


def test_databricks_script_is_unity_catalog_read_only():
    g = guide.build("databricks", {"principal": "nf-reader", "catalog": "main", "schemas": ["finance"]})
    sql = sql_of(g)
    assert "GRANT USE CATALOG ON CATALOG main TO `nf-reader`" in sql
    assert "GRANT SELECT ON SCHEMA main.finance TO `nf-reader`" in sql
    assert not re.search(r"MODIFY|ALL PRIVILEGES|OWNER|CREATE", sql.upper())
    assert g["fill"]["catalog"] == "main" and g["fill"]["schema"] == "finance"


@pytest.mark.parametrize("bad", ["x; DROP TABLE y", "a'b", 'a"b', "1abc", "a-b", "a.b", "a" * 200, "x`y"])
def test_names_that_could_inject_sql_are_refused(bad):
    with pytest.raises(SourceError):
        guide.build("snowflake", {"database": bad})
    with pytest.raises(SourceError):
        guide.build("snowflake", {"database": "OK", "role": bad})
    with pytest.raises(SourceError):
        guide.build("snowflake", {"database": "OK", "schemas": bad})
    with pytest.raises(SourceError):
        guide.build("databricks", {"principal": "p", "catalog": bad})


def test_databricks_principal_cannot_break_out_of_its_quotes():
    for bad in ["a`; DROP", "x`y", "a'b", "a;b"]:
        with pytest.raises(SourceError):
            guide.build("databricks", {"principal": bad, "catalog": "c"})


def test_database_is_required_and_other_types_have_no_guide():
    with pytest.raises(SourceError):
        guide.build("snowflake", {})
    with pytest.raises(SourceError):
        guide.build("sftp", {})


def test_network_step_lists_egress_ips_only_when_configured(monkeypatch):
    plain = sql_of(guide.build("snowflake", {"database": "D"}))
    assert "NETWORK POLICY" not in plain
    monkeypatch.setenv("NEURAFLOW_EGRESS_IPS", "203.0.113.5, 198.51.100.0/24, evil; DROP")
    g = guide.build("snowflake", {"database": "D"})
    sql = sql_of(g)
    assert "ALLOWED_IP_LIST = ('203.0.113.5', '198.51.100.0/24')" in sql and "evil" not in sql
    assert "203.0.113.5" in sql_of(guide.build("databricks", {"principal": "p", "catalog": "c"}))


def test_guide_endpoint_returns_steps_and_rejects_bad_input(api, monkeypatch):
    r = api.post("/data/setup-guide", json={"type": "snowflake", "params": {"database": "FIN"}})
    assert r.status_code == 200 and len(r.json()["steps"]) >= 5 and r.json()["egress_ips"] == []
    assert api.post("/data/setup-guide", json={"type": "snowflake", "params": {"database": "x; drop"}}).status_code == 400
    monkeypatch.delenv("ALLOW_OPEN_DATA_ADMIN")
    assert api.post("/data/setup-guide", json={"type": "snowflake", "params": {"database": "FIN"}}).status_code == 403


# ------------------------------------------------------------------ error explanations

@pytest.mark.parametrize("msg,code", [
    ("250001 (08001): Failed to connect to DB. Incorrect username or password was specified.", "BAD_CREDENTIALS"),
    ("390189 (08004): Role 'NF_ROLE' specified in the connect string does not exist or not authorized.", "BAD_ROLE"),
    ("000606 (57P03): No active warehouse selected in the current session.", "NO_WAREHOUSE"),
    ("002003 (42S02): SQL compilation error: Object 'FIN.ERP.INVOICES' does not exist or not authorized.", "NO_ACCESS"),
    ("250001 (08001): Failed to connect to DB: x.snowflakecomputing.com:443. IP 1.2.3.4 is not allowed to access Snowflake. Contact your account administrator.", "NETWORK_BLOCKED"),
    ("JWT token is invalid.", "BAD_KEY"),
    ("Failed to connect to DB: acme.snowflakecomputing.com:443. Max retries exceeded with url", "UNREACHABLE"),
    ("[Errno -2] Name or service not known", "UNREACHABLE"),
    ("Invalid access token. 401 Unauthorized", "BAD_TOKEN"),
    ("PERMISSION_DENIED: User does not have USE CATALOG on Catalog 'main'.", "NO_ACCESS"),
    ("[TABLE_OR_VIEW_NOT_FOUND] The table or view `main`.`fin`.`inv` cannot be found.", "NO_ACCESS"),
    ("Catalog 'mian' not found", "BAD_LOCATION"),
    ("TEMPORARILY_UNAVAILABLE: warehouse is starting", "WAREHOUSE_STARTING"),
    ("Invalid HTTP path 404 Not Found", "BAD_HTTP_PATH"),
    ("Request blocked by IP access list", "NETWORK_BLOCKED"),
])
def test_common_warehouse_errors_get_a_plain_explanation(msg, code):
    d = diagnose.diagnose(msg)
    assert d and d["code"] == code, (msg, d)
    assert d["title"] and d["fix"]


def test_unrecognised_errors_get_no_made_up_hint():
    assert diagnose.diagnose("something odd happened") is None
    assert diagnose.diagnose("") is None


def test_api_attaches_the_hint_but_keeps_the_databases_own_message(api, monkeypatch):
    def boom(c):
        class R:
            def test(self):
                raise SourceError("The database said: 390189 (08004): Role 'X' specified in the connect string does not exist or not authorized.")
        return R()
    monkeypatch.setattr(service, "_reader", boom)
    cid = api.post("/data/connections", json={"name": "W", "type": "databricks", "params": {"server_hostname": "h", "http_path": "/p", "access_token": "t"}}).json()["id"]
    r = api.post(f"/data/connections/{cid}/test")
    d = r.json()["detail"]
    assert r.status_code == 400 and d["code"] == "BAD_ROLE" and "Role 'X'" in d["message"] and d["hint"]["fix"]


# ------------------------------------------------------------------ connection check

class FakeWarehouse:
    def __init__(self, objs):
        self.objs = objs

    def test(self):
        pass

    def objects(self):
        return self.objs


def mk(api):
    return api.post("/data/connections", json={"name": "W", "type": "snowflake", "params": {"account": "a", "user": "u", "password": "p"}}).json()["id"]


def test_check_reports_how_many_tables_are_visible(api, monkeypatch):
    monkeypatch.setattr(service, "_reader", lambda c: FakeWarehouse([{"name": "A.B"}, {"name": "A.C"}]))
    r = api.post(f"/data/connections/{mk(api)}/test").json()
    assert r["ok"] and r["tables"] == 2 and "2 tables and views" in r["message"] and "warning" not in r
    monkeypatch.setattr(service, "_reader", lambda c: FakeWarehouse([{"name": "A.B"}]))
    assert "1 table and view." in api.post(f"/data/connections/{mk(api)}/test").json()["message"]


def test_connecting_with_no_visible_tables_is_a_warning_not_a_success(api, monkeypatch):
    monkeypatch.setattr(service, "_reader", lambda c: FakeWarehouse([]))
    r = api.post(f"/data/connections/{mk(api)}/test").json()
    assert r["ok"] and r["tables"] == 0 and "can't see any tables" in r["message"] and "SELECT" in r["warning"]
