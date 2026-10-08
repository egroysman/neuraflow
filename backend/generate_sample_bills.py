"""Generate the sample vendor-bills dataset (neuraflow_bills.csv).

The bills mirror the sample invoice book: same date range, vendor spend sized
to a plausible share of revenue, and a mix of vendors that are paid early, on
time and late. Deterministic (seeded) so the file is reproducible:

    python generate_sample_bills.py
"""
import csv
import datetime as dt
import random
from pathlib import Path

AS_OF = dt.date(2026, 4, 9)  # newest invoice date in neuraflow_invoices.csv
START = dt.date(2025, 10, 21)

# vendor id, name, category, terms days, monthly spend, our habit: mean days paid after due, spread
VENDORS = [
    ("V100", "Northwind Components", "Cost of sales", 45, 38000, 6, 5),
    ("V101", "Apex Materials", "Cost of sales", 30, 31000, 0, 4),
    ("V102", "Harbor Freight & Logistics", "Cost of sales", 30, 17500, -2, 3),
    ("V103", "Summit Contract Labor", "Cost of sales", 15, 24000, 0, 2),
    ("V104", "Lakeshore Packaging", "Cost of sales", 45, 12500, 14, 8),
    ("V105", "Prairie Utilities", "Facilities", 20, 6200, 0, 2),
    ("V106", "Cedar Property Mgmt", "Facilities", 30, 18000, -3, 1),
    ("V107", "CloudStack Hosting", "Software", 30, 9800, 0, 3),
    ("V108", "Orbit SaaS Suite", "Software", 30, 7400, 2, 3),
    ("V109", "Meridian Legal LLP", "Professional services", 45, 8800, 21, 12),
    ("V110", "Bright Accounting Group", "Professional services", 30, 5600, 5, 4),
    ("V111", "Evergreen Insurance", "Insurance", 60, 7900, 0, 2),
    ("V112", "Pioneer Marketing Co", "Marketing", 30, 11200, 9, 7),
    ("V113", "Delta Equipment Service", "Maintenance", 30, 4300, 18, 10),
]


def main() -> None:
    rng = random.Random(42)
    rows = []
    bill_id = 1
    day = START
    while day <= AS_OF:
        # each vendor bills roughly monthly, on a vendor-specific cycle day
        for vid, name, cat, terms, monthly, habit, spread in VENDORS:
            cycle = 7 + (sum(map(ord, vid)) % 21)
            if day.day != cycle:
                continue
            for part in range(1 if monthly < 15000 else 2):
                amount = monthly / (1 if monthly < 15000 else 2) * rng.uniform(0.85, 1.18)
                bill_date = day + dt.timedelta(days=part * 11)
                if bill_date > AS_OF:
                    continue
                due = bill_date + dt.timedelta(days=terms)
                paid = due + dt.timedelta(days=round(rng.gauss(habit, spread)))
                paid = max(paid, bill_date + dt.timedelta(days=3))
                if paid > AS_OF:
                    status, pay, open_amt = "Open", "", round(amount, 2)
                else:
                    status, pay, open_amt = "Paid", paid.isoformat(), 0.0
                rows.append(
                    [bill_id, vid, name, cat, bill_date.isoformat(), due.isoformat(),
                     round(amount, 2), pay, status, open_amt, terms]
                )
                bill_id += 1
        day += dt.timedelta(days=1)
    path = Path(__file__).with_name("neuraflow_bills.csv")
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["BillID", "VendorID", "VendorName", "Category", "BillDate", "DueDate",
                    "BillAmount", "PaymentDate", "Status", "OpenAmount", "TermsDays"])
        w.writerows(rows)
    print(f"wrote {len(rows)} bills to {path}")


if __name__ == "__main__":
    main()
