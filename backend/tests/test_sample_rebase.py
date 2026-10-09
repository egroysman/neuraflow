"""The bundled sample is rolled forward so the forecast starts today, and only the sample is."""
import datetime as dt

import pytest

from cashflow import ap, ar, engine, gl, sample

D = dt.date


@pytest.fixture
def on(monkeypatch):
    monkeypatch.setenv("SAMPLE_REBASE", "on")


@pytest.fixture
def off(monkeypatch):
    monkeypatch.setenv("SAMPLE_REBASE", "off")


def test_months_to_shift(on):
    assert sample.months_to_shift(D(2026, 10, 9)) == 6
    assert sample.months_to_shift(D(2026, 10, 8)) == 5  # not yet a full six months
    assert sample.months_to_shift(D(2026, 4, 9)) == 0
    assert sample.months_to_shift(D(2026, 1, 1)) == 0  # never shifts backwards


def test_switch_off(off):
    assert sample.months_to_shift(D(2030, 1, 1)) == 0


def test_shift_keeps_every_gap_inside_a_row():
    rows = [{"InvoiceDate": "2026-01-31", "DueDate": "2026-03-02", "PaymentDate": "2026-03-20", "X": "keep"}]
    out = sample.shift_rows(rows, "InvoiceDate", ("DueDate", "PaymentDate"), months=1)[0]
    assert out["InvoiceDate"] == "2026-02-28"  # month end is clamped
    gap = lambda r, a, b: (D.fromisoformat(r[b]) - D.fromisoformat(r[a])).days
    for a, b in (("InvoiceDate", "DueDate"), ("InvoiceDate", "PaymentDate")):
        assert gap(out, a, b) == gap(rows[0], a, b)
    assert out["X"] == "keep" and rows[0]["InvoiceDate"] == "2026-01-31"  # input untouched


def test_blank_payment_dates_stay_blank():
    out = sample.shift_rows([{"InvoiceDate": "2026-01-10", "DueDate": "2026-02-10", "PaymentDate": ""}], "InvoiceDate", ("DueDate", "PaymentDate"), months=3)[0]
    assert out["PaymentDate"] == "" and out["InvoiceDate"] == "2026-04-10"


def test_forecast_starts_in_the_current_month(on, monkeypatch):
    monkeypatch.setattr(sample, "months_to_shift", lambda today=None: 6)
    rows = ar.load_invoice_rows()
    inv = ar.parse_invoices(rows)
    assert ar.snapshot_date(inv) == D(2026, 10, 9)


def test_all_sample_files_move_by_the_same_months(on, monkeypatch):
    monkeypatch.setattr(sample, "months_to_shift", lambda today=None: 6)
    inv = ar.parse_invoices(ar.load_invoice_rows())
    bills = ap.parse_bills(ap.load_bill_rows())
    journal = gl.load_gl()["journal"]
    assert min(i.invoice_date for i in inv) >= D(2026, 4, 1)
    assert min(b.bill_date for b in bills) >= D(2026, 5, 1)
    assert min(r["Date"] for r in journal) == "2026-04-01" and max(r["Date"] for r in journal) <= "2026-10-31"
    moved = [r["HireDate"] for r in gl.load_payroll_rows()]
    monkeypatch.setattr(sample, "months_to_shift", lambda today=None: 0)
    orig = [r["HireDate"] for r in gl.load_payroll_rows()]
    assert moved == [sample.add_months(D.fromisoformat(x), 6).isoformat() for x in orig]


def test_behaviour_is_unchanged_by_the_shift(monkeypatch):
    monkeypatch.setenv("SAMPLE_REBASE", "off")
    base = ar.parse_invoices(ar.load_invoice_rows())
    monkeypatch.setenv("SAMPLE_REBASE", "on")
    monkeypatch.setattr(sample, "months_to_shift", lambda today=None: 6)
    moved = ar.parse_invoices(ar.load_invoice_rows())
    lag = lambda xs: sorted(((i.payment_date - i.due_date).days if i.payment_date else None) or -999 for i in xs)
    assert lag(base) == lag(moved)
    assert sorted(i.amount for i in base) == sorted(i.amount for i in moved)


def test_your_own_data_is_never_moved(on, monkeypatch, tmp_path):
    monkeypatch.setattr(sample, "months_to_shift", lambda today=None: 6)
    p = tmp_path / "mine.csv"
    p.write_text("InvoiceID,CustomerID,Behavior,InvoiceDate,DueDate,InvoiceAmount,PaymentDate,Status,OpenAmount,TermsDays\n1,C1,good,2025-01-05,2025-02-04,100,2025-02-10,Paid,0,30\n")
    monkeypatch.setenv("DEFAULT_INVOICE_CSV_PATH", str(p))
    monkeypatch.setenv("DATA_SOURCE_TYPE", "snowflake")  # force the plain file fallback
    monkeypatch.setattr("data_sources.get_data_source", lambda: (_ for _ in ()).throw(RuntimeError()), raising=False)
    assert ar.load_invoice_rows()[0]["InvoiceDate"] == "2025-01-05"
