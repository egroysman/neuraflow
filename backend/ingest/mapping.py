"""Suggest a column mapping, apply it, and check what came out."""
from __future__ import annotations

import datetime as dt
import difflib
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional, Sequence

from .parsing import detect_day_first, is_blank, parse_date, parse_number, share_parsing
from .schemas import DATASETS, MODEL_LINES, Dataset, Field

MAX_SAMPLE = 200
AUTO_THRESHOLD = 0.6


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", re.sub(r"([a-z])([A-Z])", r"\1 \2", str(s)).lower())).strip()


def _name_score(column: str, f: Field) -> float:
    c = _norm(column)
    if not c:
        return 0.0
    cands = {_norm(f.name), _norm(f.label), *(_norm(s) for s in f.synonyms)}
    if c in cands:
        return 1.0
    ctoks = set(c.split())
    best = 0.0
    for cand in cands:
        if not cand:
            continue
        ratio = difflib.SequenceMatcher(None, c, cand).ratio()
        toks = set(cand.split())
        jac = len(ctoks & toks) / len(ctoks | toks) if ctoks | toks else 0.0
        best = max(best, ratio * 0.9, jac * 0.9)
    return best


def _column_values(rows: Sequence[Dict[str, Any]], column: str) -> List[Any]:
    return [r.get(column) for r in rows[:MAX_SAMPLE]]


def suggest_mapping(dataset: Dataset, columns: Sequence[str], rows: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """Best column for each field, with a confidence and a plain reason. One column is used once."""
    scored = []
    for f in dataset.fields:
        for col in columns:
            ns = _name_score(col, f)
            if ns < 0.45:
                continue
            vals = _column_values(rows, col)
            nonblank = [v for v in vals if not is_blank(v)]
            if f.kind == "date":
                compat = share_parsing(vals, "date")
            elif f.kind in ("number", "int"):
                compat = share_parsing(vals, "number")
            else:
                compat = 1.0 if nonblank else 0.3
            if f.kind != "text" and compat < 0.6:
                continue
            scored.append((ns * 0.75 + compat * 0.25, ns, compat, f, col))
    scored.sort(key=lambda t: (-t[0], t[3].name))
    out: Dict[str, Dict[str, Any]] = {}
    used_cols: set = set()
    for score, ns, compat, f, col in scored:
        if f.name in out or col in used_cols or score < AUTO_THRESHOLD:
            continue
        out[f.name] = {"column": col, "confidence": round(score, 2), "reason": "same name" if ns >= 1.0 else "similar name"}
        used_cols.add(col)
    return out


def sample_values(rows: Sequence[Dict[str, Any]], column: str, n: int = 3) -> List[str]:
    seen: List[str] = []
    for r in rows[:MAX_SAMPLE]:
        v = r.get(column)
        if is_blank(v):
            continue
        s = v.isoformat() if isinstance(v, (dt.date, dt.datetime)) else str(v)
        if s not in seen:
            seen.append(s)
        if len(seen) >= n:
            break
    return seen


# ----------------------------------------------------------------- ledger helpers

def normalize_account_type(raw: str) -> Optional[str]:
    s = _norm(raw)
    if not s:
        return None
    if re.search(r"\b(expense|cost of|cogs|overhead)\b", s):
        return "Expense"
    if re.search(r"\b(revenue|income|sales)\b", s):
        return "Revenue"
    if re.search(r"\b(equity|capital|retained|owner|shareholder)\b", s):
        return "Equity"
    if re.search(r"\b(liabilit|payable|credit card|loan|debt|accrued|deferred revenue)\b", s):
        return "Liability"
    if re.search(r"\b(asset|bank|cash|receivable|inventory|prepaid|fixed|equipment|property)\b", s):
        return "Asset"
    return None


def infer_model_line(acct_type: str, subtype: str, name: str) -> str:
    text = _norm(f"{subtype} {name}")
    has = lambda pat: re.search(pat, text) is not None  # noqa: E731
    if acct_type == "Asset":
        if has(r"\b(cash|bank|checking|savings|petty|money market)\b"):
            return "cash"
        if has(r"\b(receivable|a r|ar)\b"):
            return "ar"
        if has(r"\b(fixed|equipment|property|vehicle|furniture|machinery|building|computer|leasehold|accumulated depreciation)\b"):
            return "ppe"
        return "other"
    if acct_type == "Liability":
        if has(r"\b(loan|note|notes|debt|line of credit|mortgage|term|borrowing)\b") and not has(r"\b(payroll|tax)\b"):
            return "debt"
        if has(r"\b(payable|credit card|ap|a p)\b") and not has(r"\b(payroll|tax|interest)\b"):
            return "ap"
        return "other"
    if acct_type == "Equity":
        return "equity"
    if acct_type == "Revenue":
        return "revenue"
    if acct_type == "Expense":
        if has(r"\b(cost of goods|cost of sales|cost of revenue|cogs|direct cost|direct materials|materials|freight in|subcontract)\b"):
            return "cogs"
        if has(r"\b(depreciation|amortization|amortisation)\b"):
            return "depreciation"
        if has(r"\binterest\b"):
            return "interest"
        if has(r"\b(payroll|salar|wage|benefit|bonus|employee|compensation|401k|payroll tax)\b"):
            return "payroll"
        label = re.sub(r"[:]", " ", str(name or subtype or "Other")).strip()[:40] or "Other"
        return f"opex:{label}"
    return "other"


def valid_model_line(v: str) -> bool:
    return v in MODEL_LINES or (v.startswith("opex:") and len(v) > 5)


def _id(v: Any) -> str:
    if isinstance(v, float) and v == int(v):
        v = int(v)
    s = str(v).strip()
    return s[:-2] if re.fullmatch(r"\d+\.0", s) else s


# ----------------------------------------------------------------- apply

def _empty_report(n_in: int) -> Dict[str, Any]:
    return {"rows_in": n_in, "rows_out": 0, "dropped": Counter(), "notes": [], "inferred": {}}


def _get(row: Dict[str, Any], mapping: Dict[str, Optional[str]], name: str) -> Any:
    col = mapping.get(name)
    return row.get(col) if col else None


def _date_ctx(dataset: Dataset, rows: Sequence[Dict[str, Any]], mapping: Dict[str, Optional[str]], options: Dict[str, Any]) -> Dict[str, bool]:
    """Per date field: is the day first? Decided from the whole column, or by the user's choice."""
    forced = options.get("date_order")  # "DMY" | "MDY" | None
    ctx: Dict[str, bool] = {}
    for f in dataset.fields:
        if f.kind != "date" or not mapping.get(f.name):
            continue
        if forced in ("DMY", "MDY"):
            ctx[f.name] = forced == "DMY"
        else:
            ctx[f.name] = bool(detect_day_first([r.get(mapping[f.name]) for r in rows]))
    return ctx


def apply_mapping(dataset_key: str, rows: Sequence[Dict[str, Any]], mapping: Dict[str, Optional[str]], options: Optional[Dict[str, Any]] = None):
    """Turn source rows into the canonical rows the forecast reads. Returns (rows, report)."""
    ds = DATASETS[dataset_key]
    options = options or {}
    mapping = {k: v for k, v in mapping.items() if v}
    report = _empty_report(len(rows))
    dfirst = _date_ctx(ds, rows, mapping, options)
    D = lambda row, name: parse_date(_get(row, mapping, name), dfirst.get(name, False))  # noqa: E731
    N = lambda row, name: parse_number(_get(row, mapping, name))  # noqa: E731
    T = lambda row, name: ("" if is_blank(_get(row, mapping, name)) else str(_get(row, mapping, name)).strip())  # noqa: E731
    iso = lambda d: d.isoformat() if d else ""  # noqa: E731
    out: List[Dict[str, Any]] = []
    drop = report["dropped"]

    if dataset_key in ("invoices", "bills"):
        inv = dataset_key == "invoices"
        amt, dte, ident = ("InvoiceAmount", "InvoiceDate", "InvoiceID") if inv else ("BillAmount", "BillDate", "BillID")
        paid_no_date = 0
        for i, r in enumerate(rows, 1):
            if inv and not T(r, "CustomerID"):
                drop["missing customer"] += 1
                continue
            if not inv and not (T(r, "VendorID") or T(r, "VendorName")):
                drop["missing vendor"] += 1
                continue
            d0 = D(r, dte)
            if d0 is None:
                drop[f"unreadable {'invoice' if inv else 'bill'} date"] += 1
                continue
            a = N(r, amt)
            if a is None:
                drop["unreadable amount"] += 1
                continue
            if a <= 0:
                drop["zero or negative amount (credit memos)"] += 1
                continue
            paid, due = D(r, "PaymentDate"), D(r, "DueDate")
            terms = N(r, "TermsDays")
            if terms is None or terms <= 0:
                terms = float((due - d0).days) if due and due >= d0 else 30.0
            if due is None:
                due = d0 + dt.timedelta(days=int(terms))
            status_raw = T(r, "Status").lower()
            is_paid = paid is not None or status_raw in ("paid", "closed", "settled", "cleared")
            if is_paid and paid is None:
                paid_no_date += 1
            open_amt = 0.0 if is_paid else (N(r, "OpenAmount") or a)
            row = {ident: T(r, ident) or str(i), "Status": "Paid" if is_paid else "Open", dte: iso(d0), "DueDate": iso(due),
                   amt: round(a, 2), "PaymentDate": iso(paid), "OpenAmount": round(open_amt, 2), "TermsDays": int(terms)}
            if inv:
                row["CustomerID"] = T(r, "CustomerID")
            else:
                vid, vn = T(r, "VendorID"), T(r, "VendorName")
                row.update({"VendorID": vid or vn, "VendorName": vn or vid, "Category": T(r, "Category") or "Other"})
            out.append(row)
        if paid_no_date:
            report["notes"].append(f"{paid_no_date} rows are marked paid but have no payment date, so they cannot show how the customer pays.")

    elif dataset_key == "gl_accounts":
        overrides = {_id(k): v for k, v in (options.get("account_overrides") or {}).items() if valid_model_line(str(v))}
        seen: set = set()
        unknown_types = 0
        for r in rows:
            aid = _id(_get(r, mapping, "AccountID") if mapping.get("AccountID") else "")
            name = T(r, "AccountName")
            if not aid or not name:
                drop["missing account number or name"] += 1
                continue
            if aid in seen:
                drop["duplicate account number"] += 1
                continue
            seen.add(aid)
            raw_type = T(r, "AccountType")
            atype = normalize_account_type(raw_type) or normalize_account_type(f"{T(r, 'Subtype')} {name}")
            if atype is None:
                unknown_types += 1
                atype = raw_type or "Unknown"
            sub = T(r, "Subtype") or raw_type
            given = T(r, "ModelLine")
            ml = given if given and valid_model_line(given) else infer_model_line(atype, sub, name)
            inferred = not (given and valid_model_line(given))
            if aid in overrides:
                ml, inferred = overrides[aid], False
            if inferred:
                report["inferred"][aid] = ml
            out.append({"AccountID": aid, "AccountName": name, "AccountType": atype, "Subtype": sub, "ModelLine": ml})
        if unknown_types:
            report["notes"].append(f"{unknown_types} accounts have a type NeuraFlow does not recognise.")

    elif dataset_key == "gl_journal":
        for i, r in enumerate(rows, 1):
            aid = _id(_get(r, mapping, "AccountID") if mapping.get("AccountID") else "")
            d0 = D(r, "Date")
            if not aid:
                drop["missing account"] += 1
                continue
            if d0 is None:
                drop["unreadable date"] += 1
                continue
            deb, cre, sgn = N(r, "Debit"), N(r, "Credit"), N(r, "SignedAmount")
            if deb is None and cre is None and sgn is None:
                drop["no amount"] += 1
                continue
            if deb is None and cre is None:
                deb, cre = max(sgn, 0.0), max(-sgn, 0.0)
            deb, cre = deb or 0.0, cre or 0.0
            if deb < 0 or cre < 0:  # a negative debit is a credit
                deb, cre = max(deb, 0.0) + max(-cre, 0.0), max(cre, 0.0) + max(-deb, 0.0)
            if deb == 0 and cre == 0:
                drop["zero amount"] += 1
                continue
            out.append({"EntryID": T(r, "EntryID") or f"L{i}", "Date": iso(d0), "AccountID": aid,
                        "Debit": round(deb, 2), "Credit": round(cre, 2), "Memo": T(r, "Memo"), "Source": T(r, "Source")})

    elif dataset_key == "payroll":
        seen_e: set = set()
        for r in rows:
            eid = _id(_get(r, mapping, "EmployeeID") if mapping.get("EmployeeID") else "")
            if not eid:
                drop["missing employee id"] += 1
                continue
            if eid in seen_e:
                drop["duplicate employee id"] += 1
                continue
            seen_e.add(eid)
            sal, hr = N(r, "AnnualSalary"), N(r, "HourlyRate")
            pt = T(r, "PayType").lower()
            pt = "hourly" if pt.startswith("h") or (not pt and not sal and hr) else "salary"
            out.append({"EmployeeID": eid, "Department": T(r, "Department") or "General", "Title": T(r, "Title"), "PayType": pt,
                        "AnnualSalary": round(sal, 2) if sal else "", "HourlyRate": round(hr, 2) if hr else "",
                        "HoursPerWeek": N(r, "HoursPerWeek") or (40 if pt == "hourly" else ""), "HireDate": iso(D(r, "HireDate")),
                        "TermDate": iso(D(r, "TermDate")), "BonusPct": N(r, "BonusPct") or 0, "BenefitsMonthly": N(r, "BenefitsMonthly") or 0})
    report["rows_out"] = len(out)
    report["dropped"] = dict(drop)
    amb = [f.label for f in ds.fields if f.kind == "date" and mapping.get(f.name) and options.get("date_order") is None
           and any(isinstance(r.get(mapping[f.name]), str) and re.match(r"\s*\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}", r.get(mapping[f.name]) or "") for r in rows[:50])
           and detect_day_first([r.get(mapping[f.name]) for r in rows]) is None]
    if amb:
        report["notes"].append(f"Dates like 03/04/2026 in {', '.join(amb)} could be day-first or month-first. Read as month-first; change this if it is wrong.")
        report["ambiguous_dates"] = True
    return out, report


# ----------------------------------------------------------------- validate

def _range(vals: Sequence[str]) -> Optional[List[str]]:
    v = sorted(x for x in vals if x)
    return [v[0], v[-1]] if v else None


def validate(dataset_key: str, rows: Sequence[Dict[str, Any]], report: Dict[str, Any], mapping: Dict[str, Optional[str]], extra: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Plain-language checks on the mapped data. level: error blocks loading, warning does not."""
    ds = DATASETS[dataset_key]
    mapping = {k: v for k, v in mapping.items() if v}
    issues: List[Dict[str, str]] = []
    add = lambda level, msg: issues.append({"level": level, "message": msg})  # noqa: E731
    for f in ds.fields:
        if f.required and f.name not in mapping:
            add("error", f"No column chosen for {f.label}.")
    for group in ds.at_least_one_of:
        if not any(n in mapping for n in group):
            add("error", "Choose a column for at least one of: " + ", ".join(ds.field(n).label for n in group) + ".")
    n = len(rows)
    if n == 0:
        add("error", "No usable rows after mapping." + (" Rows were dropped: " + ", ".join(f"{v} {k}" for k, v in report["dropped"].items()) + "." if report["dropped"] else ""))
    for k, v in report["dropped"].items():
        share = v / max(1, report["rows_in"])
        add("warning" if share < 0.2 else "error" if share > 0.5 else "warning", f"{v} of {report['rows_in']} rows dropped: {k}.")
    for note in report["notes"]:
        add("warning", note)
    stats: Dict[str, Any] = {"rows": n}
    if n and not any(i["level"] == "error" for i in issues):
        if n < ds.min_rows_warn:
            add("warning", f"Only {n} rows. Results will be rough with fewer than {ds.min_rows_warn}.")
        if dataset_key == "invoices":
            paid = sum(1 for r in rows if r["PaymentDate"])
            stats.update({"customers": len({r["CustomerID"] for r in rows}), "paid_share": round(paid / n, 3), "date_range": _range([r["InvoiceDate"] for r in rows])})
            if paid == 0:
                add("warning", "No invoice has a payment date, so NeuraFlow cannot learn how customers pay. Forecasts will use generic assumptions.")
            elif paid / n < 0.3:
                add("warning", f"Only {paid / n:.0%} of invoices have a payment date.")
            ids = Counter(r["InvoiceID"] for r in rows)
            dup = sum(1 for v in ids.values() if v > 1)
            if dup:
                add("warning", f"{dup} invoice numbers appear more than once.")
        elif dataset_key == "bills":
            paid = sum(1 for r in rows if r["PaymentDate"])
            stats.update({"vendors": len({r["VendorID"] for r in rows}), "paid_share": round(paid / n, 3), "date_range": _range([r["BillDate"] for r in rows])})
            if paid == 0:
                add("warning", "No bill has a payment date, so vendor payment timing cannot be learned.")
        elif dataset_key == "gl_accounts":
            lines = Counter(r["ModelLine"].split(":")[0] for r in rows)
            stats["lines"] = dict(lines)
            for need, label in (("cash", "cash"), ("revenue", "revenue")):
                if not lines.get(need):
                    add("warning", f"No {label} account found. Check the NeuraFlow line for your accounts.")
            if report["inferred"]:
                add("info", f"{len(report['inferred'])} accounts were classified from their type and name. Review them below.")
        elif dataset_key == "gl_journal":
            dr, cr = sum(r["Debit"] for r in rows), sum(r["Credit"] for r in rows)
            stats.update({"debits": round(dr, 2), "credits": round(cr, 2), "date_range": _range([r["Date"] for r in rows])})
            if abs(dr - cr) > max(1.0, 0.001 * max(dr, cr)):
                add("warning", f"Debits and credits differ by {abs(dr - cr):,.2f}. A balanced ledger has no difference.")
            accts = (extra or {}).get("account_ids")
            if accts is not None:
                missing = sum(1 for r in rows if r["AccountID"] not in accts)
                if missing:
                    add("error" if missing / n > 0.2 else "warning", f"{missing} journal lines use accounts missing from the chart of accounts and will be ignored.")
            months = {r["Date"][:7] for r in rows}
            if len(months) < 4:
                add("warning", f"The ledger covers {len(months)} month(s). Three or more complete months are needed for baselines.")
        elif dataset_key == "payroll":
            stats["employees"] = len(rows)
            active = sum(1 for r in rows if not r["TermDate"])
            stats["active"] = active
            if not active:
                add("warning", "Every employee has a termination date.")
    return {"ok": not any(i["level"] == "error" for i in issues), "issues": issues, "stats": stats}
