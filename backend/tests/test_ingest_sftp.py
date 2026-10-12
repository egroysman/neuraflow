"""SFTP against a real in-process SSH/SFTP server: host key pinning, sign-in, newest-file pick, scheduled refresh."""
import io
import socket
import threading
import time

import paramiko
import pytest
from cryptography.fernet import Fernet

from cashflow import ar
from ingest import readers as R, service, store

HOST_KEY = paramiko.RSAKey.generate(2048)
FILES = {}  # name -> (bytes, mtime)


class Auth(paramiko.ServerInterface):
    def check_auth_password(self, username, password):
        return paramiko.AUTH_SUCCESSFUL if (username, password) == ("svc", "pw") else paramiko.AUTH_FAILED

    def get_allowed_auths(self, username):
        return "password"

    def check_channel_request(self, kind, chanid):
        return paramiko.OPEN_SUCCEEDED


class Folder(paramiko.SFTPServerInterface):
    def _attr(self, name):
        b, m = FILES[name]
        a = paramiko.SFTPAttributes()
        a.filename, a.st_size, a.st_mtime, a.st_atime, a.st_mode = name, len(b), int(m), int(m), 0o100644
        return a

    def list_folder(self, path):
        return [self._attr(n) for n in FILES]

    def stat(self, path):
        n = path.strip("./").split("/")[-1]
        return self._attr(n) if n in FILES else paramiko.SFTP_NO_SUCH_FILE

    lstat = stat

    def canonicalize(self, path):
        return "/" + path.strip("./")

    def open(self, path, flags, attr):
        n = path.strip("./").split("/")[-1]
        if n not in FILES:
            return paramiko.SFTP_NO_SUCH_FILE
        h = paramiko.SFTPHandle(flags)
        h.readfile = io.BytesIO(FILES[n][0])
        return h


@pytest.fixture
def server():
    FILES.clear()
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    sock.listen(5)
    port = sock.getsockname()[1]
    stop = threading.Event()

    def serve():
        sock.settimeout(0.2)
        while not stop.is_set():
            try:
                conn, _ = sock.accept()
            except (socket.timeout, OSError):
                continue
            t = paramiko.Transport(conn)
            t.add_server_key(HOST_KEY)
            t.set_subsystem_handler("sftp", paramiko.SFTPServer, Folder)
            try:
                t.start_server(server=Auth())
            except Exception:  # noqa: BLE001
                pass

    th = threading.Thread(target=serve, daemon=True)
    th.start()
    yield port
    stop.set()
    sock.close()


@pytest.fixture(autouse=True)
def env(monkeypatch, tmp_path):
    monkeypatch.setenv("INGEST_DIR", str(tmp_path / "store"))
    monkeypatch.setenv("CONNECTION_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("ALLOW_OPEN_DATA_ADMIN", "1")
    store._SNAP.clear()


FP = R.host_key_fingerprint(HOST_KEY)


def csv_file(n, start=0):
    return ("Customer,Invoice Date,Amount,Paid On\n" + "\n".join(f"C{i % 5},2026-01-{i % 28 + 1:02d},{100 + i},{'2026-02-10' if i % 2 else ''}" for i in range(start, start + n))).encode()


def params(port, **kw):
    return {"host": "127.0.0.1", "port": port, "username": "svc", "password": "pw", "directory": ".", **kw}


def test_an_unpinned_server_is_reported_with_its_fingerprint_and_nothing_is_sent(server):
    c = store.save_connection("Drop", "sftp", params(server))
    r = service.test_connection(c["id"])
    assert r["ok"] is False and r["needs_host_key"] and r["host_key_sha256"] == FP
    assert service.observe_host_key(params(server)) == FP


def test_a_wrong_pin_is_refused_before_credentials_are_sent(server):
    c = store.save_connection("Drop", "sftp", params(server, host_key_sha256="SHA256:" + "A" * 43))
    with pytest.raises(R.SourceError, match="does not match"):
        service.test_connection(c["id"])


def test_pinned_connection_signs_in_lists_and_picks_the_newest_matching_file(server):
    FILES["invoices_2026-09.csv"] = (csv_file(40), time.time() - 5000)
    FILES["invoices_2026-10.csv"] = (csv_file(60), time.time() - 100)
    FILES["notes.pdf"] = (b"x", time.time())
    c = store.save_connection("Drop", "sftp", params(server, host_key_sha256=FP))
    assert service.test_connection(c["id"])["ok"]
    names = [o["name"] for o in service.list_objects({"kind": "connection", "connection_id": c["id"]})]
    assert names == ["invoices_2026-10.csv", "invoices_2026-09.csv"] and "notes.pdf" not in names
    a = service.analyze("invoices", {"kind": "connection", "connection_id": c["id"], "object": "invoices_*.csv"})
    assert a["row_count"] == 60 and a["validation"]["ok"] and a["mapping"]["CustomerID"] == "Customer"


def test_wrong_password_and_path_tricks_are_rejected(server):
    bad = store.save_connection("Bad", "sftp", params(server, host_key_sha256=FP, password="nope"))
    with pytest.raises(R.SourceError, match="sign-in failed"):
        service.test_connection(bad["id"])
    ok = store.save_connection("Ok", "sftp", params(server, host_key_sha256=FP))
    for evil in ("../etc/passwd", "a/b.csv", "..\\x.csv"):
        with pytest.raises(R.SourceError, match="without folders"):
            service.read_source({"kind": "connection", "connection_id": ok["id"], "object": evil})
    with pytest.raises(R.SourceError, match="No file matching"):
        service.read_source({"kind": "connection", "connection_id": ok["id"], "object": "missing*.csv"})


def test_a_scheduled_refresh_picks_up_the_newer_file_over_real_sftp(server):
    FILES["invoices_1.csv"] = (csv_file(60), time.time() - 5000)
    c = store.save_connection("Drop", "sftp", params(server, host_key_sha256=FP))
    src = {"kind": "connection", "connection_id": c["id"], "object": "invoices_*.csv"}
    a = service.analyze("invoices", src)
    service.save_dataset("invoices", src, a["mapping"], {}, {"mode": "interval", "every_minutes": 60})
    assert len(ar.load_invoice_rows()) == 60
    FILES["invoices_2.csv"] = (csv_file(75), time.time())
    assert service.due_datasets(time.time()) == []
    assert service.due_datasets(time.time() + 3700) == ["invoices"]
    run = service.refresh_dataset("invoices", "schedule")
    assert run["ok"] and run["rows_out"] == 75 and len(ar.load_invoice_rows()) == 75
    assert service.status()["datasets"][0]["last_run"]["trigger"] == "schedule"


def test_the_scheduler_thread_loads_and_refreshes_without_anyone_clicking(server, monkeypatch):
    FILES["invoices_1.csv"] = (csv_file(60), time.time() - 5000)
    monkeypatch.setenv("SFTP_HOST", "127.0.0.1")
    monkeypatch.setenv("SFTP_PORT", str(server))
    monkeypatch.setenv("SFTP_USERNAME", "svc")
    monkeypatch.setenv("SFTP_PASSWORD", "pw")
    monkeypatch.setenv("SFTP_HOST_KEY_SHA256", FP)
    monkeypatch.setenv("SFTP_PATTERN_INVOICES", "invoices_*.csv")
    monkeypatch.setenv("SFTP_SCHEDULE", "every 15m")
    try:
        service.start_scheduler(interval=0.2)
        for _ in range(50):
            if ar.load_invoice_rows() and len(ar.load_invoice_rows()) == 60:
                break
            time.sleep(0.2)
        assert len(ar.load_invoice_rows()) == 60  # loaded by ghost mode with no user action
        assert service.status()["datasets"][0]["schedule"] == {"mode": "interval", "every_minutes": 15}
    finally:
        service.stop_scheduler()
