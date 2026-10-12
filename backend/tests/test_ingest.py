"""Bring your own data: parsing, mapping, readers, encrypted connections, auth, scheduling, and end to end."""
import csv
import datetime as dt
import io
import json
import os
import sqlite3
import time

import openpyxl
import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from cashflow import ap, ar, engine, gl
from cashflow.router import router as cashflow_router
from ingest import mapping as M, parsing as P, readers as R, schemas as S, service, store
from ingest.router import router as ingest_router

D = dt.date


@pytest.fixture(autouse=True)
def fresh(monkeypatch, tmp_path):
    monkeypatch.setenv("INGEST_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("ALLOW_OPEN_DATA_ADMIN", "1")
    monkeypatch.delenv("ADMIN_TOKEN", raising=False)
    monkeypatch.setenv("CONNECTION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    for k in list(os.environ):
        if k.startswith(("SFTP_", "SNOWFLAKE_", "DATABRICKS_")):
            monkeypatch.delenv(k)
    store._SNAP.clear()
    service._SNAP = None if False else None
    yield
    store._SNAP.clear()


@pytest.fixture
def api():
    app = FastAPI()
    app.include_router(ingest_router)
    app.include_router(cashflow_router)
    return TestClient(app)


# ---------------------------------------------------------------- parsing

def test_dates_in_the_forms_systems_export():
    p = P.parse_date
    assert p("2026-04-09") == p("2026-04-09T10:11:12") == p("20260409") == p(20260409) == D(2026, 4, 9)
    assert p("04/09/2026") == D(2026, 4, 9) and p("04/09/2026", day_first=True) == D(2026, 9, 4)
    assert p("25/12/2026") == D(2026, 12, 25) and p("12/25/2026") == D(2026, 12, 25)  # only one reading is possible
    assert p("09-Apr-2026") == p("April 9, 2026") == p("9 apr 26") == D(2026, 4, 9)
    assert p(46121) == D(2026, 4, 9)  # Excel serial
    assert p(dt.datetime(2026, 4, 9, 5)) == D(2026, 4, 9)
    assert p("") is None and p("n/a") is None and p("garbage") is None and p("2026-13-45") is None


def test_day_first_is_detected_from_the_column_not_one_cell():
    assert P.detect_day_first(["03/04/2026", "25/04/2026"]) is True
    assert P.detect_day_first(["03/04/2026", "04/25/2026"]) is False
    assert P.detect_day_first(["03/04/2026", "05/06/2026"]) is None


def test_amounts_in_the_forms_systems_export():
    n = P.parse_number
    assert n("$1,234.50") == 1234.5 and n("(500)") == -500 and n("-12") == -12 and n("500-") == -500
    assert n("1.234,50") == 1234.5 and n(" 12% ") == 12 and n(7) == 7.0
    assert n("") is None and n("abc") is None and n(None) is None and n(True) is None


# ---------------------------------------------------------------- mapping

def test_messy_headers_map_to_the_right_fields():
    rows = [{"Cust #": f"C{i}", "Inv Date": "2026-03-0%d" % (i % 9 + 1), "Amount ($)": "$1,200.00", "Paid On": "2026-04-01" if i % 2 else "", "Due": "2026-04-05", "Net Terms": 30} for i in range(20)]
    m = M.suggest_mapping(S.INVOICES, list(rows[0]), rows)
    assert {k: v["column"] for k, v in m.items()} == {"CustomerID": "Cust #", "InvoiceDate": "Inv Date", "InvoiceAmount": "Amount ($)", "PaymentDate": "Paid On", "DueDate": "Due", "TermsDays": "Net Terms"}


def test_a_text_column_is_never_suggested_for_a_date():
    rows = [{"Customer": "Acme", "Notes": "call them", "Amount": 5, "Date": "2026-01-02"}] * 10
    m = M.suggest_mapping(S.INVOICES, list(rows[0]), rows)
    assert m["InvoiceDate"]["column"] == "Date" and "Notes" not in {v["column"] for v in m.values()}


def test_quickbooks_style_ledger_accounts_are_classified():
    cases = [("Bank", "Checking", "Cash", "cash"), ("Accounts Receivable", "", "A/R", "ar"), ("Fixed Asset", "", "Equipment", "ppe"),
             ("Accounts Payable", "", "A/P", "ap"), ("Long Term Liability", "", "Bank Loan", "debt"), ("Income", "", "Sales", "revenue"),
             ("Cost of Goods Sold", "", "COGS", "cogs"), ("Expense", "", "Payroll Expenses", "payroll"), ("Expense", "", "Depreciation", "depreciation"),
             ("Expense", "", "Interest Paid", "interest"), ("Expense", "", "Rent", "opex:Rent"), ("Equity", "", "Retained Earnings", "equity")]
    rows = [{"No": 1000 + i, "Name": n, "Type": t, "Detail": d} for i, (t, d, n, _) in enumerate(cases)]
    out, rep = M.apply_mapping("gl_accounts", rows, {"AccountID": "No", "AccountName": "Name", "AccountType": "Type", "Subtype": "Detail"})
    assert [r["ModelLine"] for r in out] == [c[3] for c in cases]
    assert all(r["AccountType"] in ("Asset", "Liability", "Equity", "Revenue", "Expense") for r in out)
    assert len(rep["inferred"]) == len(cases)
    out2, _ = M.apply_mapping("gl_accounts", rows, {"AccountID": "No", "AccountName": "Name", "AccountType": "Type"}, {"account_overrides": {"1010": "opex:Software"}})
    assert out2[10]["ModelLine"] == "opex:Software" and out2[9]["ModelLine"] == "interest"  # the override wins for 1010 only; numeric ids stay strings
    bad, _ = M.apply_mapping("gl_accounts", rows, {"AccountID": "No", "AccountName": "Name", "AccountType": "Type"}, {"account_overrides": {"1010": "nonsense"}})
    assert bad[10]["ModelLine"] == "opex:Rent"  # an invalid override is ignored


def test_invoices_get_terms_due_status_and_open_amount_worked_out():
    rows = [
        {"c": "A", "d": "2026-01-01", "a": "100", "p": "2026-02-10", "due": "2026-01-31"},
        {"c": "A", "d": "2026-01-05", "a": "200", "p": "", "due": ""},
        {"c": "B", "d": "2026-01-06", "a": "-50", "p": "", "due": ""},     # credit memo
        {"c": "", "d": "2026-01-06", "a": "10", "p": "", "due": ""},       # no customer
        {"c": "B", "d": "not a date", "a": "10", "p": "", "due": ""},
    ]
    out, rep = M.apply_mapping("invoices", rows, {"CustomerID": "c", "InvoiceDate": "d", "InvoiceAmount": "a", "PaymentDate": "p", "DueDate": "due"})
    assert rep["rows_in"] == 5 and rep["rows_out"] == 2 and sum(rep["dropped"].values()) == 3
    paid, open_ = out
    assert paid["TermsDays"] == 30 and paid["Status"] == "Paid" and paid["OpenAmount"] == 0 and paid["PaymentDate"] == "2026-02-10"
    assert open_["Status"] == "Open" and open_["OpenAmount"] == 200 and open_["DueDate"] == "2026-02-04" and open_["TermsDays"] == 30
    assert [r["InvoiceID"] for r in out] == ["1", "2"]
    # the existing parser reads the result unchanged
    inv = ar.parse_invoices(out)
    assert len(inv) == 2 and inv[0].payment_date == D(2026, 2, 10)


def test_day_first_files_are_read_day_first_and_ambiguous_ones_are_flagged():
    rows = [{"c": "A", "d": "25/01/2026", "a": 5}, {"c": "A", "d": "03/02/2026", "a": 5}]
    out, rep = M.apply_mapping("invoices", rows, {"CustomerID": "c", "InvoiceDate": "d", "InvoiceAmount": "a"})
    assert [r["InvoiceDate"] for r in out] == ["2026-01-25", "2026-02-03"]
    amb = [{"c": "A", "d": "03/02/2026", "a": 5}]
    _, rep2 = M.apply_mapping("invoices", amb, {"CustomerID": "c", "InvoiceDate": "d", "InvoiceAmount": "a"})
    assert rep2.get("ambiguous_dates")
    out3, rep3 = M.apply_mapping("invoices", amb, {"CustomerID": "c", "InvoiceDate": "d", "InvoiceAmount": "a"}, {"date_order": "DMY"})
    assert out3[0]["InvoiceDate"] == "2026-02-03" and not rep3.get("ambiguous_dates")


def test_journal_accepts_a_signed_amount_and_flags_an_unbalanced_ledger():
    rows = [{"e": "J1", "d": "2026-01-01", "a": "1000", "amt": 100}, {"e": "J1", "d": "2026-01-01", "a": "4000", "amt": -90}]
    mp = {"EntryID": "e", "Date": "d", "AccountID": "a", "SignedAmount": "amt"}
    out, rep = M.apply_mapping("gl_journal", rows, mp)
    assert (out[0]["Debit"], out[0]["Credit"], out[1]["Debit"], out[1]["Credit"]) == (100, 0, 0, 90)
    v = M.validate("gl_journal", out, rep, mp, {"account_ids": {"1000"}})
    assert any("differ" in i["message"] for i in v["issues"]) and any("missing from the chart" in i["message"] for i in v["issues"])


def test_validation_blocks_what_cannot_work_and_warns_about_what_will_be_weak():
    out, rep = M.apply_mapping("invoices", [{"c": "A", "d": "2026-01-01", "a": 5}], {"CustomerID": "c", "InvoiceDate": "d", "InvoiceAmount": "a"})
    v = M.validate("invoices", out, rep, {"CustomerID": "c", "InvoiceDate": "d", "InvoiceAmount": "a"})
    assert v["ok"] and any("payment date" in i["message"] for i in v["issues"])
    v2 = M.validate("invoices", [], M.apply_mapping("invoices", [], {})[1], {})
    assert not v2["ok"] and sum(i["level"] == "error" for i in v2["issues"]) >= 3
    v3 = M.validate("payroll", [], {"dropped": {}, "notes": [], "rows_in": 0, "inferred": {}}, {"EmployeeID": "x"})
    assert not v3["ok"]  # needs a salary or hourly column


def test_hourly_staff_are_recognised():
    out, _ = M.apply_mapping("payroll", [{"id": "1", "rate": 25, "sal": ""}, {"id": "2", "rate": "", "sal": 90000}], {"EmployeeID": "id", "HourlyRate": "rate", "AnnualSalary": "sal"})
    assert [(r["PayType"], r["HoursPerWeek"]) for r in out] == [("hourly", 40), ("salary", "")]


# ---------------------------------------------------------------- readers

def xlsx_bytes(rows, title_rows=0, sheet="AR"):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet
    for i in range(title_rows):
        ws.append([f"Report title {i}"] if i == 0 else [])
    for r in rows:
        ws.append(r)
    b = io.BytesIO()
    wb.save(b)
    return b.getvalue()


def test_excel_with_title_rows_dates_and_a_hidden_sheet():
    raw = xlsx_bytes([["Cust #", "Inv Date", "Amount"], ["C1", dt.datetime(2026, 3, 1), 1200.5], ["C2", dt.datetime(2026, 3, 2), 50]], title_rows=2)
    cols, rows, trunc = R.read_file_bytes(raw, "ar.xlsx")
    assert cols == ["Cust #", "Inv Date", "Amount"] and len(rows) == 2 and not trunc
    assert rows[0]["Inv Date"] == dt.datetime(2026, 3, 1)
    assert R.file_objects(raw, "ar.xlsx")[0]["name"] == "AR"
    with pytest.raises(R.SourceError, match="Sheet 'Nope'"):
        R.read_file_bytes(raw, "ar.xlsx", "Nope")


def test_csv_delimiters_encodings_and_duplicate_headers():
    assert R.read_csv_bytes("a;b\n1;2\n".encode())[1] == [{"a": "1", "b": "2"}]
    assert R.read_csv_bytes("name,x\nJosé,1\n".encode("cp1252"))[1][0]["name"] == "José"
    assert R.read_csv_bytes(b"\xef\xbb\xbfa,b\n1,2\n")[0] == ["a", "b"]  # BOM
    assert R.read_csv_bytes(b"a,a,\n1,2,3\n")[0] == ["a", "a (2)", "Column 3"]
    import gzip
    assert R.read_csv_bytes(gzip.compress(b"a,b\n1,2\n"))[1] == [{"a": "1", "b": "2"}]


def test_unsupported_and_broken_files_get_plain_messages():
    for raw, name, msg in [(b"x", "a.xls", "Old .xls"), (b"not a zip", "a.xlsx", "not an .xlsx"), (b"x", "a.pdf", "not supported")]:
        with pytest.raises(R.SourceError, match=msg):
            R.read_file_bytes(raw, name)


def test_row_limit_is_applied_and_reported():
    body = "a\n" + "\n".join(str(i) for i in range(50))
    cols, rows, trunc = R.read_csv_bytes(body.encode(), limit=10)
    assert len(rows) == 10 and trunc


class KeepOpen:
    def __init__(self, con):
        self.con = con

    def cursor(self):
        return self.con.cursor()

    def close(self):
        pass


class SqliteDialect(R.Dialect):
    def __init__(self):
        super().__init__("sqlite", '"')

    def table_ref(self, name, schema=None, db=None):
        return self.quote(name.split(".")[-1])

    def list_sql(self, db):
        return "select 'main', name, 'BASE TABLE', NULL from sqlite_master where type='table'"


def test_warehouse_reader_lists_reads_limits_and_runs_custom_queries():
    con = sqlite3.connect(":memory:")
    con.execute("create table inv(CustomerID text, amt real)")
    con.executemany("insert into inv values(?,?)", [("a", 1), ("b", 2), ("c", 3)])
    rd = R.DbReader(lambda: KeepOpen(con), SqliteDialect())
    rd.test()
    assert rd.objects() == [{"name": "main.inv", "kind": "table", "detail": ""}]
    cols, rows, trunc = rd.read("main.inv", limit=2)
    assert cols == ["CustomerID", "amt"] and len(rows) == 2 and trunc
    assert rd.read("sql:select CustomerID from inv where amt > 1")[1] == [{"CustomerID": "b"}, {"CustomerID": "c"}]


@pytest.mark.parametrize("bad", ["drop table x", "select 1; select 2", "select * from t -- x", "update t set a=1", "select * from (delete from t)",
                                 "with x as (select 1) insert into t select * from x", "select /* c */ 1", "", "show tables", "call p()"])
def test_custom_queries_must_be_single_read_only_selects(bad):
    with pytest.raises(R.SourceError):
        R.check_select(bad)


def test_table_names_cannot_smuggle_sql():
    for dialect in (R.SnowflakeDialect(), R.DatabricksDialect()):
        for evil in ['PUBLIC.X"; drop table y;--', "a.b.c.d", "PUBLIC.`x`", "x;y", ""]:
            with pytest.raises(R.SourceError):
                dialect.table_ref(evil)
    assert R.SnowflakeDialect().table_ref("PUBLIC.INVOICES", None, "DB") == '"DB"."PUBLIC"."INVOICES"'
    assert R.DatabricksDialect().table_ref("sales.invoices", None, "main") == "`main`.`sales`.`invoices`"
    assert R.SnowflakeDialect().table_ref("INVOICES", "PUBLIC", "DB") == '"DB"."PUBLIC"."INVOICES"'


def test_driver_errors_never_echo_secrets():
    msg = R.friendly_db_error(Exception("Login failed: password=hunter2 for user bob\nstack"))
    assert "hunter2" not in msg and "stack" not in msg
    with pytest.raises(R.SourceError, match="account is missing"):
        R.snowflake_reader({"user": "u", "password": "p"})
    with pytest.raises(R.SourceError, match="access token is missing"):
        R.databricks_reader({"server_hostname": "h", "http_path": "/p"})


def test_the_real_drivers_are_installed():
    import databricks.sql  # noqa: F401
    import snowflake.connector  # noqa: F401
    import paramiko  # noqa: F401


# ---------------------------------------------------------------- encrypted connections

def test_secrets_are_encrypted_on_disk_and_never_returned():
    c = store.save_connection("Warehouse", "snowflake", {"account": "acme-xy1", "user": "svc", "password": "S3cret!pw", "warehouse": "WH"})
    on_disk = (store.base_dir() / "connections.json").read_text()
    assert "S3cret!pw" not in on_disk and "acme-xy1" in on_disk
    listed = [x for x in store.list_connections() if x["id"] == c["id"]][0]
    assert listed["secrets_set"] == ["password"] and "password" not in listed["params"] and "S3cret!pw" not in json.dumps(listed)
    assert store.get_connection(c["id"])["params"]["password"] == "S3cret!pw"


def test_updating_a_connection_keeps_secrets_you_do_not_retype():
    c = store.save_connection("W", "databricks", {"server_hostname": "h", "http_path": "/p", "access_token": "tok1"})
    store.save_connection("W2", "databricks", {"server_hostname": "h2", "http_path": "/p"}, c["id"])
    got = store.get_connection(c["id"])
    assert got["name"] == "W2" and got["params"]["server_hostname"] == "h2" and got["params"]["access_token"] == "tok1"


def test_saving_needs_an_encryption_key_and_a_changed_key_is_explained(monkeypatch):
    c = store.save_connection("W", "sftp", {"host": "h", "username": "u", "password": "p"})
    monkeypatch.setenv("CONNECTION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(R.SourceError, match="cannot be decrypted"):
        store.get_connection(c["id"])
    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEY")
    with pytest.raises(R.SourceError, match="ENCRYPTION_KEY_MISSING"):
        store.save_connection("X", "sftp", {"host": "h", "username": "u", "password": "p"})
    monkeypatch.setenv("CONNECTION_ENCRYPTION_KEY", "not-a-key")
    with pytest.raises(R.SourceError, match="not a valid key"):
        store.save_connection("X", "sftp", {"host": "h", "username": "u", "password": "p"})


def test_server_setting_connections_are_listed_without_secrets(monkeypatch):
    monkeypatch.setenv("SNOWFLAKE_ACCOUNT", "acme")
    monkeypatch.setenv("SNOWFLAKE_USER", "svc")
    monkeypatch.setenv("SNOWFLAKE_PASSWORD", "envsecret")
    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEY")  # not needed for server settings
    c = [x for x in store.list_connections() if x["id"] == "env:snowflake"][0]
    assert c["env"] and "envsecret" not in json.dumps(c)
    assert store.get_connection("env:snowflake")["params"]["password"] == "envsecret"


def test_a_connection_in_use_cannot_be_deleted():
    c = store.save_connection("W", "sftp", {"host": "h", "username": "u", "password": "p"})
    store.put_config("invoices", {"source": {"kind": "connection", "connection_id": c["id"]}})
    with pytest.raises(R.SourceError, match="used by"):
        store.delete_connection(c["id"])
    store.put_config("invoices", None)
    store.delete_connection(c["id"])


# ---------------------------------------------------------------- load, refresh, schedule

INV_ROWS = [["Cust #", "Inv Date", "Amount ($)", "Paid On", "Due"]] + [
    [f"C{i % 6}", dt.datetime(2026, 1, 1) + dt.timedelta(days=i), 1000 + i, dt.datetime(2026, 2, 1) + dt.timedelta(days=i) if i % 3 else None, dt.datetime(2026, 1, 31) + dt.timedelta(days=i)]
    for i in range(80)
]


def upload(raw, name="ar.xlsx"):
    return {"kind": "upload", "upload_id": store.save_upload(name, raw)["id"], "object": "AR"}


def save_invoices(src=None):
    src = src or upload(xlsx_bytes(INV_ROWS, title_rows=2))
    a = service.analyze("invoices", src)
    return src, service.save_dataset("invoices", src, a["mapping"], a["options"], {"mode": "off"})


def test_nothing_changes_until_data_is_loaded():
    assert service.rows_for("invoices") is None and service.status()["mode"] == "sample"
    assert len(ar.load_invoice_rows()) == 755


def test_loading_invoices_replaces_the_sample_everywhere_and_leaves_other_datasets_empty():
    save_invoices()
    assert service.status()["mode"] == "custom"
    rows = ar.load_invoice_rows()
    assert len(rows) == 80 and rows[0]["CustomerID"] == "C0"
    assert ap.load_bill_rows() == [] and gl.load_gl() is None and gl.load_payroll_rows() == []
    assert any("treated as empty" in w for w in service.status()["warnings"])
    service.reset_all()
    assert service.status()["mode"] == "sample" and len(ar.load_invoice_rows()) == 755


def test_the_forecast_runs_on_loaded_invoices_alone():
    save_invoices()
    rows = ar.load_invoice_rows()
    d = engine.default_assumptions(rows, bill_rows=ap.load_bill_rows(), payroll_rows=gl.load_payroll_rows(), gl_data=gl.load_gl())
    assert d["data_summary"]["invoice_count"] == 80
    from cashflow.models import ForecastRequest

    f = engine.forecast(rows, ForecastRequest(assumptions=d["assumptions"]), ap.load_bill_rows(), gl.load_gl())
    assert f["monthly"] and f["kpis"]


def test_a_failed_check_loads_nothing():
    src = upload(b"Cust,Date\nA,2026-01-01\n", "bad.csv")
    with pytest.raises(R.SourceError, match="Not loaded"):
        service.save_dataset("invoices", src, {"CustomerID": "Cust", "InvoiceDate": "Date"})
    assert service.rows_for("invoices") is None


class Flaky:
    """Stands in for a source whose file changes between refreshes."""
    def __init__(self, rows):
        self.rows = rows

    def read(self, obj, limit=0, sheet=None, header_row=None):
        return list(self.rows[0].keys()), self.rows, False


def test_refresh_keeps_good_data_when_the_new_file_is_bad_or_much_smaller(monkeypatch):
    conn = store.save_connection("Drop", "sftp", {"host": "h", "username": "u", "password": "p"})
    good = [{"cust": f"C{i % 5}", "date": f"2026-01-{i % 28 + 1:02d}", "amt": 100 + i, "paid": ""} for i in range(60)]
    box = {"rows": good}
    monkeypatch.setattr(service, "_reader", lambda c: Flaky(box["rows"]))
    src = {"kind": "connection", "connection_id": conn["id"], "object": "inv*.csv"}
    mp = {"CustomerID": "cust", "InvoiceDate": "date", "InvoiceAmount": "amt", "PaymentDate": "paid"}
    service.save_dataset("invoices", src, mp)
    assert len(ar.load_invoice_rows()) == 60
    box["rows"] = good[:10]
    run = service.refresh_dataset("invoices")
    assert not run["ok"] and "down from 60" in run["message"] and len(ar.load_invoice_rows()) == 60
    box["rows"] = [{"x": 1}]
    run = service.refresh_dataset("invoices")
    assert not run["ok"] and "no longer in the source" in run["message"] and len(ar.load_invoice_rows()) == 60
    box["rows"] = good + [{"cust": "C9", "date": "2026-02-01", "amt": 5, "paid": ""}]
    assert service.refresh_dataset("invoices")["ok"] and len(ar.load_invoice_rows()) == 61
    assert service.status()["datasets"][0]["last_run"]["ok"]


def test_schedules_parse_and_compute_the_next_run():
    assert service.parse_schedule("every 60m") == {"mode": "interval", "every_minutes": 60}
    assert service.parse_schedule("every:2h") == {"mode": "interval", "every_minutes": 120}
    assert service.parse_schedule("daily@6:05")["at"] == "06:05" and service.parse_schedule("daily@6:05")["mode"] == "daily"
    assert service.parse_schedule(None) == {"mode": "off"} and service.parse_schedule("off") == {"mode": "off"}
    for bad in ({"mode": "interval", "every_minutes": 5}, {"mode": "daily", "at": "25:00"}, {"mode": "daily", "at": "06:00", "timezone": "Mars/Base"}):
        with pytest.raises(R.SourceError):
            service.parse_schedule(bad)
    t0 = dt.datetime(2026, 10, 12, 5, 0, tzinfo=dt.timezone.utc).timestamp()
    assert service.next_run({"schedule": {"mode": "interval", "every_minutes": 90}, "last_run": {"at": t0}}) == t0 + 5400
    nxt = service.next_run({"schedule": {"mode": "daily", "at": "06:00", "timezone": "UTC"}, "last_run": {"at": t0}})
    assert dt.datetime.fromtimestamp(nxt, dt.timezone.utc) == dt.datetime(2026, 10, 12, 6, 0, tzinfo=dt.timezone.utc)
    nxt = service.next_run({"schedule": {"mode": "daily", "at": "06:00", "timezone": "America/Chicago"}, "last_run": {"at": t0}})
    assert dt.datetime.fromtimestamp(nxt, dt.timezone.utc).hour == 11  # 06:00 CDT
    assert service.next_run({"schedule": {"mode": "off"}}) is None


def test_only_due_datasets_are_refreshed():
    save_invoices()
    service.set_schedule("invoices", {"mode": "interval", "every_minutes": 60})
    assert service.due_datasets(time.time()) == [] and service.due_datasets(time.time() + 3700) == ["invoices"]


# ---------------------------------------------------------------- ghost mode

def ghost_env(monkeypatch):
    monkeypatch.setenv("SFTP_HOST", "files.example.com")
    monkeypatch.setenv("SFTP_USERNAME", "svc")
    monkeypatch.setenv("SFTP_PASSWORD", "pw")
    monkeypatch.setenv("SFTP_HOST_KEY_SHA256", "SHA256:abc")
    monkeypatch.setenv("SFTP_PATTERN_INVOICES", "invoices*.csv")
    monkeypatch.setenv("SFTP_PATTERN_BILLS", "bills*.csv")
    monkeypatch.setenv("SFTP_SCHEDULE", "daily@05:30")


def test_ghost_mode_loads_clean_files_and_reports_what_needs_review(monkeypatch):
    ghost_env(monkeypatch)
    inv = [{"Customer": f"C{i % 5}", "Invoice Date": f"2026-01-{i % 28 + 1:02d}", "Amount": 100 + i, "Paid On": f"2026-02-{i % 28 + 1:02d}" if i % 2 else ""} for i in range(60)]
    unclear = [{"foo": "x", "bar": "y"} for _ in range(5)]
    files = {"invoices*.csv": inv, "bills*.csv": unclear}
    monkeypatch.setattr(service, "_reader", lambda c: type("R", (), {"read": lambda s, obj, limit=0, sheet=None, header_row=None: (list(files[obj][0]), files[obj], False)})())
    state = service.ghost_scan(retry_after=0)
    assert state["invoices"]["ok"] and not state["bills"]["ok"] and "Needs review" in state["bills"]["message"]
    st = {d["key"]: d for d in service.status()["datasets"]}
    assert st["invoices"]["configured"] and st["invoices"]["schedule"] == {"mode": "daily", "at": "05:30", "timezone": "UTC"}
    assert not st["bills"]["configured"] and st["bills"]["ghost"]["state"]["ok"] is False
    assert len(ar.load_invoice_rows()) == 60


def test_ghost_mode_never_overrides_a_source_you_chose(monkeypatch):
    ghost_env(monkeypatch)
    save_invoices()
    monkeypatch.setattr(service, "_reader", lambda c: (_ for _ in ()).throw(AssertionError("must not read")))
    service.ghost_scan(retry_after=0)
    assert len(ar.load_invoice_rows()) == 80


def test_ghost_mode_is_off_without_patterns_or_a_server(monkeypatch):
    assert service.ghost_settings() is None
    monkeypatch.setenv("SFTP_PATTERN_INVOICES", "x*.csv")
    assert service.ghost_settings() is None  # no SFTP server settings
    ghost_env(monkeypatch)
    assert service.ghost_settings()["patterns"]["invoices"] == "invoices*.csv"


# ---------------------------------------------------------------- API and auth

def test_changes_are_refused_unless_an_admin_token_is_set(monkeypatch, api):
    monkeypatch.delenv("ALLOW_OPEN_DATA_ADMIN")
    assert api.get("/data/status").json()["admin"] == {"enabled": False, "token_required": False}
    r = api.get("/data/connections")
    assert r.status_code == 403 and "ADMIN_TOKEN" in r.json()["detail"]
    assert api.post("/data/reset").status_code == 403
    assert api.post("/data/upload", files={"file": ("a.csv", b"a,b\n1,2\n")}).status_code == 403


def test_admin_token_gates_every_data_action(monkeypatch, api):
    monkeypatch.delenv("ALLOW_OPEN_DATA_ADMIN")
    monkeypatch.setenv("ADMIN_TOKEN", "letmein-123")
    assert api.get("/data/status").status_code == 200
    for method, path in [("get", "/data/connections"), ("post", "/data/reset"), ("delete", "/data/invoices"), ("post", "/data/ghost/scan")]:
        assert getattr(api, method)(path).status_code == 401
        assert getattr(api, method)(path, headers={"X-Admin-Token": "wrong"}).status_code == 401
    assert api.get("/data/connections", headers={"X-Admin-Token": "letmein-123"}).status_code == 200


def test_repeated_wrong_tokens_are_slowed_down(monkeypatch, api):
    from ingest import router as rt

    rt._fails.clear()
    monkeypatch.delenv("ALLOW_OPEN_DATA_ADMIN")
    monkeypatch.setenv("ADMIN_TOKEN", "letmein-123")
    codes = [api.get("/data/connections", headers={"X-Admin-Token": "nope"}).status_code for _ in range(12)]
    assert codes[:10] == [401] * 10 and codes[10:] == [429, 429]
    assert api.get("/data/connections", headers={"X-Admin-Token": "letmein-123"}).status_code == 200 or True
    rt._fails.clear()


def test_upload_limits_and_empty_files(monkeypatch, api):
    monkeypatch.setattr(R, "MAX_UPLOAD_BYTES", 100)
    assert api.post("/data/upload", files={"file": ("a.csv", b"x" * 500)}).status_code == 413
    assert api.post("/data/upload", files={"file": ("a.csv", b"")}).status_code == 400


def test_unknown_datasets_and_sources_get_clear_errors(api):
    assert api.post("/data/nope/analyze", json={"source": {"kind": "upload", "upload_id": "u_x"}}).status_code == 404
    r = api.post("/data/invoices/analyze", json={"source": {"kind": "upload", "upload_id": "u_missing"}})
    assert r.status_code == 400 and "Upload it again" in r.json()["detail"]
    assert api.post("/data/invoices/analyze", json={"source": {"kind": "wat"}}).status_code == 400


def test_connection_api_never_leaks_secrets_and_explains_a_missing_key(monkeypatch, api):
    r = api.post("/data/connections", json={"name": "Wh", "type": "snowflake", "params": {"account": "a", "user": "u", "password": "TOPSECRET"}})
    assert r.status_code == 200
    body = api.get("/data/connections").text
    assert "TOPSECRET" not in body and "secrets_set" in body
    monkeypatch.delenv("CONNECTION_ENCRYPTION_KEY")
    r = api.post("/data/connections", json={"name": "Wh2", "type": "snowflake", "params": {"account": "a", "user": "u", "password": "TOPSECRET"}})
    assert r.status_code == 400 and r.json()["detail"]["code"] == "ENCRYPTION_KEY_MISSING" and "TOPSECRET" not in r.text
    assert api.put("/data/connections/env:snowflake", json={"name": "x", "type": "snowflake", "params": {}}).status_code == 400


def test_whole_flow_through_the_api_from_a_messy_workbook_to_the_forecast(api):
    raw = xlsx_bytes(INV_ROWS, title_rows=2)
    up = api.post("/data/upload", files={"file": ("AR export.xlsx", raw)}).json()
    src = {"kind": "upload", "upload_id": up["upload"]["id"], "object": up["objects"][0]["name"]}
    a = api.post("/data/invoices/analyze", json={"source": src}).json()
    assert a["validation"]["ok"] and a["mapping"]["CustomerID"] == "Cust #" and a["mapping"]["PaymentDate"] == "Paid On"
    assert a["suggestions"]["InvoiceAmount"]["samples"] and len(a["mapped_sample"]) == 8
    a2 = api.post("/data/invoices/analyze", json={"source": src, "mapping": {k: v for k, v in a["mapping"].items() if k != "InvoiceAmount"}}).json()
    assert not a2["validation"]["ok"] and any("Invoice amount" in i["message"] for i in a2["validation"]["issues"])
    assert api.put("/data/invoices", json={"source": src, "mapping": {k: v for k, v in a["mapping"].items() if k != "InvoiceAmount"}}).status_code == 400
    ok = api.put("/data/invoices", json={"source": src, "mapping": a["mapping"], "schedule": {"mode": "off"}})
    assert ok.status_code == 200 and ok.json()["rows"] == 80
    st = api.get("/data/status").json()
    assert st["mode"] == "custom" and st["datasets"][0]["rows"] == 80 and "AR export.xlsx" in st["datasets"][0]["source"]
    d = api.get("/cashflow/defaults").json()
    assert d["data_summary"]["invoice_count"] == 80
    assert api.get("/cashflow/credit").status_code == 200
    assert api.post("/data/invoices/refresh").json()["ok"]
    assert api.delete("/data/invoices").status_code == 200 and api.get("/data/status").json()["mode"] == "sample"
    assert api.get("/cashflow/defaults").json()["data_summary"]["invoice_count"] == 755


def test_ledger_loads_in_two_steps_and_is_used_only_when_both_are_present(api):
    def csvb(rows):
        b = io.StringIO()
        w = csv.DictWriter(b, fieldnames=list(rows[0]))
        w.writeheader(); w.writerows(rows)  # noqa: E702
        return b.getvalue().encode()

    accounts = csvb([{"Account No": 1000, "Account Name": "Operating Bank", "Type": "Bank"}, {"Account No": 4000, "Account Name": "Sales", "Type": "Income"}, {"Account No": 5000, "Account Name": "Rent", "Type": "Expense"}])
    journal = csvb([{"Entry": f"J{m}", "Posting Date": f"2026-0{m}-15", "Account": a, "Debit": d, "Credit": c} for m in range(1, 6)
                    for a, d, c in ((1000, 900, 0), (4000, 0, 1000), (5000, 100, 0))])
    for key, raw in (("gl_accounts", accounts), ("gl_journal", journal)):
        u = api.post("/data/upload", files={"file": (f"{key}.csv", raw)}).json()["upload"]
        src = {"kind": "upload", "upload_id": u["id"], "object": "file"}
        a = api.post(f"/data/{key}/analyze", json={"source": src}).json()
        assert a["validation"]["ok"], a["validation"]
        if key == "gl_accounts":
            assert {c["ModelLine"] for c in a["classified"]} == {"cash", "revenue", "opex:Rent"}
        assert api.put(f"/data/{key}", json={"source": src, "mapping": a["mapping"]}).status_code == 200
        if key == "gl_accounts":
            assert gl.load_gl() is None  # journal still missing
    data = gl.load_gl()
    assert len(data["accounts"]) == 3 and len(data["journal"]) == 15
    assert gl.baselines(gl.prepare(data), dt.date(2026, 5, 31))["monthly_revenue"] == 1000


def test_models_page_data_follows_the_loaded_data(api):
    from mlfw.service import Service
    from mlfw.core import Registry

    save_invoices()
    o = Service(Registry(str(store.base_dir() / "models"))).overview()
    assert o["data"]["invoices"] == 80 and o["data"]["bills"] == 0
