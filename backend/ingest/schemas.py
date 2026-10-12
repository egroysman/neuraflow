"""The five datasets NeuraFlow understands, with the columns each one needs.

Column names are the same ones the bundled sample uses, so every parser downstream
keeps working unchanged: anything a customer loads is mapped *to* these names.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple


@dataclass(frozen=True)
class Field:
    name: str
    label: str
    kind: str  # text | date | number | int
    required: bool = False
    help: str = ""
    synonyms: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Dataset:
    key: str
    label: str
    description: str
    fields: Tuple[Field, ...]
    at_least_one_of: Tuple[Tuple[str, ...], ...] = ()
    min_rows_warn: int = 1

    def field(self, name: str) -> Field:
        return next(f for f in self.fields if f.name == name)

    @property
    def names(self) -> List[str]:
        return [f.name for f in self.fields]


INVOICES = Dataset(
    "invoices",
    "Invoices (receivables)",
    "One row per customer invoice, with the date it was paid if it has been.",
    (
        Field("InvoiceID", "Invoice number", "text", synonyms=("invoice id", "invoice number", "invoice no", "invoice #", "inv no", "doc number", "document number", "reference")),
        Field("CustomerID", "Customer", "text", True, "Who owes the money.", ("customer id", "customer", "customer name", "customer number", "client", "client id", "account", "account id", "payer", "debtor", "bill to", "sold to", "cust id")),
        Field("InvoiceDate", "Invoice date", "date", True, "When the invoice was issued.", ("invoice date", "date", "issue date", "issued", "billing date", "document date", "doc date", "posting date", "created", "txn date", "transaction date")),
        Field("DueDate", "Due date", "date", False, "If missing, invoice date plus terms.", ("due date", "due", "payment due", "payment due date", "date due", "maturity date")),
        Field("InvoiceAmount", "Invoice amount", "number", True, "Total billed.", ("invoice amount", "amount", "total", "total amount", "gross amount", "invoice total", "billed", "billed amount", "original amount", "net amount")),
        Field("PaymentDate", "Payment date", "date", False, "Blank while unpaid. Without it NeuraFlow cannot learn how customers pay.", ("payment date", "paid date", "date paid", "paid on", "cleared date", "receipt date", "received date", "settlement date", "collected date", "payment received date")),
        Field("TermsDays", "Payment terms (days)", "int", False, "Net days. Worked out from the dates if missing.", ("terms days", "terms", "payment terms", "net days", "net terms", "credit days")),
        Field("OpenAmount", "Open balance", "number", False, "Still owed. Worked out if missing.", ("open amount", "balance", "outstanding", "outstanding amount", "amount due", "balance due", "amount open", "remaining", "remaining amount", "open balance")),
        Field("Status", "Status", "text", False, "Paid or Open. Worked out from the payment date if missing.", ("status", "invoice status", "payment status", "paid status", "state")),
    ),
    min_rows_warn=50,
)

BILLS = Dataset(
    "bills",
    "Vendor bills (payables)",
    "One row per bill from a supplier, with the date it was paid if it has been.",
    (
        Field("BillID", "Bill number", "text", synonyms=("bill id", "bill number", "bill no", "bill #", "voucher", "voucher number", "invoice number", "reference", "document number")),
        Field("VendorID", "Vendor id", "text", False, "Vendor id or name is needed.", ("vendor id", "vendor", "vendor number", "supplier id", "supplier", "supplier number", "payee id", "creditor")),
        Field("VendorName", "Vendor name", "text", False, "", ("vendor name", "supplier name", "payee", "payee name", "name", "creditor name")),
        Field("Category", "Category", "text", False, "Cost of sales, rent, software and so on.", ("category", "expense category", "gl category", "account", "account name", "expense account", "cost type", "type")),
        Field("BillDate", "Bill date", "date", True, "When the bill was received.", ("bill date", "date", "invoice date", "document date", "doc date", "posting date", "received date", "txn date", "transaction date")),
        Field("DueDate", "Due date", "date", False, "If missing, bill date plus terms.", ("due date", "due", "payment due", "payment due date", "date due")),
        Field("BillAmount", "Bill amount", "number", True, "Total of the bill.", ("bill amount", "amount", "total", "total amount", "gross amount", "invoice amount", "bill total")),
        Field("PaymentDate", "Payment date", "date", False, "Blank while unpaid.", ("payment date", "paid date", "date paid", "paid on", "cleared date", "settlement date", "check date")),
        Field("TermsDays", "Payment terms (days)", "int", False, "", ("terms days", "terms", "payment terms", "net days", "net terms")),
        Field("OpenAmount", "Open balance", "number", False, "", ("open amount", "balance", "outstanding", "amount due", "balance due", "remaining")),
        Field("Status", "Status", "text", False, "", ("status", "bill status", "payment status", "state")),
    ),
    at_least_one_of=(("VendorID", "VendorName"),),
    min_rows_warn=20,
)

GL_ACCOUNTS = Dataset(
    "gl_accounts",
    "Ledger: chart of accounts",
    "One row per general ledger account.",
    (
        Field("AccountID", "Account number", "text", True, "", ("account id", "account number", "account no", "account code", "acct", "acct no", "gl account", "code", "number", "account")),
        Field("AccountName", "Account name", "text", True, "", ("account name", "name", "description", "account description", "title", "fully qualified name")),
        Field("AccountType", "Account type", "text", True, "Asset, Liability, Equity, Revenue or Expense. Common ERP names are recognised.", ("account type", "type", "class", "classification", "category", "account class", "detail type")),
        Field("Subtype", "Subtype", "text", False, "", ("subtype", "sub type", "account subtype", "detail type", "sub category", "subcategory", "group")),
        Field("ModelLine", "NeuraFlow line", "text", False, "cash, ar, ap, ppe, debt, equity, revenue, cogs, payroll, depreciation, interest or opex:<name>. Worked out from the type and name if missing.", ("model line", "modelline", "neuraflow line", "forecast line", "mapping")),
    ),
    min_rows_warn=5,
)

GL_JOURNAL = Dataset(
    "gl_journal",
    "Ledger: journal lines",
    "One row per journal line (a debit or a credit to an account).",
    (
        Field("EntryID", "Journal entry", "text", True, "Lines with the same entry belong together.", ("entry id", "journal entry", "journal id", "je", "je number", "entry number", "entry", "transaction id", "txn id", "document number", "voucher", "batch")),
        Field("Date", "Date", "date", True, "", ("date", "posting date", "transaction date", "entry date", "txn date", "journal date", "gl date", "period date")),
        Field("AccountID", "Account number", "text", True, "Must match the chart of accounts.", ("account id", "account number", "account", "account code", "acct", "gl account", "account no")),
        Field("Debit", "Debit", "number", False, "Debit and credit, or one signed amount.", ("debit", "debits", "debit amount", "dr")),
        Field("Credit", "Credit", "number", False, "", ("credit", "credits", "credit amount", "cr")),
        Field("SignedAmount", "Signed amount", "number", False, "Use only if there is no debit/credit pair. Debits positive, credits negative.", ("amount", "signed amount", "net amount", "value")),
        Field("Memo", "Memo", "text", False, "", ("memo", "description", "narrative", "line description", "note", "notes", "comment")),
        Field("Source", "Source", "text", False, "", ("source", "source system", "journal type", "type", "origin")),
    ),
    at_least_one_of=(("Debit", "Credit", "SignedAmount"),),
    min_rows_warn=50,
)

PAYROLL = Dataset(
    "payroll",
    "Payroll roster",
    "One row per employee.",
    (
        Field("EmployeeID", "Employee id", "text", True, "", ("employee id", "employee", "employee number", "emp id", "emp no", "staff id", "worker id", "id")),
        Field("Department", "Department", "text", False, "", ("department", "dept", "cost center", "cost centre", "team", "division")),
        Field("Title", "Job title", "text", False, "", ("title", "job title", "position", "role")),
        Field("PayType", "Pay type", "text", False, "salary or hourly. Worked out from the pay fields if missing.", ("pay type", "pay basis", "compensation type", "salary or hourly", "flsa", "worker type")),
        Field("AnnualSalary", "Annual salary", "number", False, "", ("annual salary", "salary", "annual pay", "base salary", "annual comp", "annual compensation", "yearly salary")),
        Field("HourlyRate", "Hourly rate", "number", False, "", ("hourly rate", "hourly", "rate", "pay rate", "wage", "hourly wage")),
        Field("HoursPerWeek", "Hours per week", "number", False, "", ("hours per week", "weekly hours", "hours", "standard hours", "scheduled hours")),
        Field("HireDate", "Hire date", "date", False, "", ("hire date", "start date", "date hired", "employment start", "joined")),
        Field("TermDate", "Termination date", "date", False, "Blank while employed.", ("term date", "termination date", "end date", "separation date", "date terminated", "last day")),
        Field("BonusPct", "Bonus %", "number", False, "", ("bonus pct", "bonus %", "bonus percent", "bonus", "target bonus")),
        Field("BenefitsMonthly", "Benefits per month", "number", False, "", ("benefits monthly", "monthly benefits", "benefits", "benefit cost", "benefits cost")),
    ),
    at_least_one_of=(("AnnualSalary", "HourlyRate"),),
    min_rows_warn=1,
)

DATASETS: Dict[str, Dataset] = {d.key: d for d in (INVOICES, BILLS, GL_ACCOUNTS, GL_JOURNAL, PAYROLL)}
ORDER = list(DATASETS)

# Valid values for the NeuraFlow ledger line, plus any "opex:<name>".
MODEL_LINES = ("cash", "ar", "ap", "ppe", "debt", "equity", "revenue", "cogs", "payroll", "depreciation", "interest", "other")
