"""Generate a sample general ledger that ties to the sample invoices, bills and payroll roster.

Writes neuraflow_gl_accounts.csv (chart of accounts) and neuraflow_gl_journal.csv
(balanced journal lines). History runs from the first invoice to the newest
invoice date (the forecast start). Everything is derived from the other sample
files, so the GL's receivables and payables equal the invoice and bill
sub-ledgers exactly. Deterministic: python generate_sample_gl.py
"""
import csv
import datetime as dt
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
D = dt.date
EMPLOYER_TAX = 0.085
TARGET_ENDING_CASH = 520_000.0
OPENING_PPE = 1_200_000.0
OPENING_ACCUM_DEP = 610_000.0
MONTHLY_DEPRECIATION = 4_200.0
LOAN_END_BALANCE = 416_000.0
LOAN_RATE = 8.0
LOAN_PAYMENT = 9_000.0

ACCOUNTS = [
    # id, name, type, subtype, model line
    ("1000", "Cash - Operating", "Asset", "Cash", "cash"),
    ("1100", "Accounts Receivable", "Asset", "Receivables", "ar"),
    ("1500", "Property & Equipment", "Asset", "Fixed assets", "ppe"),
    ("1590", "Accumulated Depreciation", "Asset", "Fixed assets", "ppe"),
    ("2000", "Accounts Payable", "Liability", "Payables", "ap"),
    ("2500", "Term Loan", "Liability", "Debt", "debt"),
    ("3000", "Paid-in Capital", "Equity", "Equity", "equity"),
    ("3900", "Retained Earnings (opening)", "Equity", "Equity", "equity"),
    ("4000", "Product Revenue", "Revenue", "Revenue", "revenue"),
    ("5000", "Cost of Sales", "Expense", "Cost of sales", "cogs"),
    ("6100", "Wages - Operations", "Expense", "Payroll", "payroll"),
    ("6110", "Wages - Sales", "Expense", "Payroll", "payroll"),
    ("6120", "Wages - Finance & Admin", "Expense", "Payroll", "payroll"),
    ("6130", "Wages - Product & Engineering", "Expense", "Payroll", "payroll"),
    ("6150", "Bonuses", "Expense", "Payroll", "payroll"),
    ("6160", "Employer Payroll Taxes", "Expense", "Payroll", "payroll"),
    ("6170", "Employee Benefits", "Expense", "Payroll", "payroll"),
    ("6200", "Rent & Facilities", "Expense", "Operating expense", "opex:Rent & facilities"),
    ("6210", "Software & Tools", "Expense", "Operating expense", "opex:Software & tools"),
    ("6220", "Professional Fees", "Expense", "Operating expense", "opex:Insurance & professional fees"),
    ("6230", "Insurance", "Expense", "Operating expense", "opex:Insurance & professional fees"),
    ("6240", "Marketing", "Expense", "Operating expense", "opex:Marketing"),
    ("6250", "Repairs & Maintenance", "Expense", "Operating expense", "opex:Rent & facilities"),
    ("6800", "Depreciation", "Expense", "Depreciation", "depreciation"),
    ("7000", "Interest Expense", "Expense", "Interest", "interest"),
]
BILL_ACCOUNT = {
    "Cost of sales": "5000", "Facilities": "6200", "Software": "6210", "Professional services": "6220",
    "Insurance": "6230", "Marketing": "6240", "Maintenance": "6250",
}
DEPT_WAGES = {"Operations": "6100", "Sales": "6110", "Finance & Admin": "6120", "Product & Engineering": "6130"}


def d(s):
    return D.fromisoformat(s) if s else None


def month_end(day):
    nxt = D(day.year + (day.month == 12), day.month % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


def main():
    invoices = list(csv.DictReader((HERE / "neuraflow_invoices.csv").open()))
    bills = list(csv.DictReader((HERE / "neuraflow_bills.csv").open()))
    roster = list(csv.DictReader((HERE / "neuraflow_payroll.csv").open()))
    as_of = max(d(r["InvoiceDate"]) for r in invoices)
    start = min(d(r["InvoiceDate"]) for r in invoices)
    start = D(start.year, start.month, 1)

    entries = []  # (date, memo, source, [(account, debit, credit)...])

    def post(date, memo, source, lines):
        lines = [(a, round(dr, 2), round(cr, 2)) for a, dr, cr in lines if round(dr, 2) or round(cr, 2)]
        diff = round(sum(x[1] for x in lines) - sum(x[2] for x in lines), 2)
        if diff:  # rounding crumbs go to the largest line
            i = max(range(len(lines)), key=lambda j: lines[j][1] + lines[j][2])
            a, dr, cr = lines[i]
            lines[i] = (a, dr, round(cr + diff, 2)) if cr or not dr else (a, round(dr - diff, 2), cr)
        entries.append((date, memo, source, lines))

    cash_flow = 0.0  # net cash movement excluding the opening balance

    for r in invoices:
        amt = float(r["InvoiceAmount"])
        inv_d = d(r["InvoiceDate"])
        post(inv_d, f"Invoice {r['InvoiceID']} {r['CustomerID']}", "AR", [("1100", amt, 0), ("4000", 0, amt)])
        pay = d(r["PaymentDate"])
        if pay and pay <= as_of:
            post(pay, f"Payment invoice {r['InvoiceID']} {r['CustomerID']}", "AR", [("1000", amt, 0), ("1100", 0, amt)])
            cash_flow += amt
    for r in bills:
        amt = float(r["BillAmount"])
        acct = BILL_ACCOUNT[r["Category"]]
        post(d(r["BillDate"]), f"Bill {r['BillID']} {r['VendorName']}", "AP", [(acct, amt, 0), ("2000", 0, amt)])
        pay = d(r["PaymentDate"])
        if pay and pay <= as_of:
            post(pay, f"Payment bill {r['BillID']} {r['VendorName']}", "AP", [("2000", amt, 0), ("1000", 0, amt)])
            cash_flow -= amt

    # --- payroll: biweekly Fridays, bonuses in December, benefits at month end
    def annual(e):
        return float(e["AnnualSalary"]) if e["PayType"] == "salary" else float(e["HourlyRate"]) * float(e["HoursPerWeek"]) * 52

    def active_fraction(e, a, b):
        hire, term = d(e["HireDate"]), d(e["TermDate"])
        lo = max(a, hire)
        hi = min(b, term + dt.timedelta(days=1)) if term else b
        return max(0, (hi - lo).days) / (b - a).days

    first_friday = start + dt.timedelta(days=(4 - start.weekday()) % 7)
    run = first_friday
    while run <= as_of:
        per_dept = defaultdict(float)
        for e in roster:
            frac = active_fraction(e, run - dt.timedelta(days=14), run)
            if frac > 0 and d(e["HireDate"]) <= as_of:
                per_dept[e["Department"]] += annual(e) / 26 * frac
        gross = sum(per_dept.values())
        if gross:
            lines = [(DEPT_WAGES[k], v, 0) for k, v in per_dept.items()]
            lines += [("6160", gross * EMPLOYER_TAX, 0)]
            total = sum(x[1] for x in lines)
            post(run, "Payroll run", "Payroll", lines + [("1000", 0, total)])
            cash_flow -= round(total, 2)
        run += dt.timedelta(days=14)
    for e in roster:  # December bonus
        pass
    bonus_day = D(2025, 12, 19)
    if start <= bonus_day <= as_of:
        bonus = 0.0
        for e in roster:
            hire, term = d(e["HireDate"]), d(e["TermDate"])
            if hire <= bonus_day and (not term or term >= bonus_day) and float(e["BonusPct"] or 0):
                year_frac = min(1.0, (bonus_day - max(hire, D(2025, 1, 1))).days / 365)
                bonus += annual(e) * float(e["BonusPct"]) / 100 * year_frac
        total = bonus * (1 + EMPLOYER_TAX)
        post(bonus_day, "Annual bonuses", "Payroll", [("6150", bonus, 0), ("6160", bonus * EMPLOYER_TAX, 0), ("1000", 0, total)])
        cash_flow -= round(total, 2)
    m = month_end(start)
    while m <= as_of:
        benefits = sum(float(e["BenefitsMonthly"]) * active_fraction(e, D(m.year, m.month, 1), m + dt.timedelta(days=1)) for e in roster if d(e["HireDate"]) <= m)
        if benefits:
            post(m, "Employee benefits", "Payroll", [("6170", benefits, 0), ("1000", 0, benefits)])
            cash_flow -= round(benefits, 2)
        post(m, "Monthly depreciation", "Depreciation", [("6800", MONTHLY_DEPRECIATION, 0), ("1590", 0, MONTHLY_DEPRECIATION)])
        m = month_end(m + dt.timedelta(days=1))

    # --- term loan: solve the opening balance so the balance at the start date is LOAN_END_BALANCE
    pay_dates = []
    day = D(start.year, start.month, 10)
    while day <= as_of:
        if day > start:
            pay_dates.append(day)
        day = D(day.year + (day.month == 12), day.month % 12 + 1, 10)

    def run_loan(opening):
        bal, rows = opening, []
        for p in pay_dates:
            interest = bal * LOAN_RATE / 100 / 12
            principal = LOAN_PAYMENT - interest
            rows.append((p, interest, principal))
            bal -= principal
        return bal, rows

    opening_loan = LOAN_END_BALANCE
    for _ in range(40):
        end_bal, rows = run_loan(opening_loan)
        opening_loan += LOAN_END_BALANCE - end_bal
    for p, interest, principal in rows:
        post(p, "Term loan payment", "Loan", [("7000", interest, 0), ("2500", principal, 0), ("1000", 0, interest + principal)])
        cash_flow -= round(interest + principal, 2)

    opening_cash = round(TARGET_ENDING_CASH - cash_flow, 2)
    assert opening_cash > 0, opening_cash
    assets = opening_cash + OPENING_PPE - OPENING_ACCUM_DEP
    capital = 400_000.0
    retained = round(assets - opening_loan - capital, 2)
    post(start, "Opening balances", "Opening",
         [("1000", opening_cash, 0), ("1500", OPENING_PPE, 0), ("1590", 0, OPENING_ACCUM_DEP),
          ("2500", 0, round(opening_loan, 2)), ("3000", 0, capital), ("3900", 0, retained)])

    entries.sort(key=lambda e: (e[0], e[2] != "Opening"))
    with (HERE / "neuraflow_gl_accounts.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["AccountID", "AccountName", "AccountType", "Subtype", "ModelLine"])
        w.writerows(ACCOUNTS)
    n = 0
    with (HERE / "neuraflow_gl_journal.csv").open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["EntryID", "Date", "AccountID", "Debit", "Credit", "Memo", "Source"])
        for i, (date, memo, source, lines) in enumerate(entries, start=1):
            for a, dr, cr in lines:
                w.writerow([f"JE{i:05d}", date.isoformat(), a, f"{dr:.2f}", f"{cr:.2f}", memo, source])
                n += 1
    print(f"wrote {len(entries)} entries / {n} lines; opening cash {opening_cash:,.0f}, opening loan {opening_loan:,.0f}")


if __name__ == "__main__":
    main()
