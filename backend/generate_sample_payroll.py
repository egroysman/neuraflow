"""Generate the sample employee roster (neuraflow_payroll.csv).

Job titles and IDs only (no personal names). Includes people hired during the
history, one who left, and two planned hires after the forecast start date.
Deterministic: python generate_sample_payroll.py
"""
import csv
from pathlib import Path

HEADER = ["EmployeeID", "Department", "Title", "PayType", "AnnualSalary", "HourlyRate",
          "HoursPerWeek", "HireDate", "TermDate", "BonusPct", "BenefitsMonthly"]

ROWS = [
    ("E001", "Operations", "Operations Manager", "salary", 98000, "", "", "2022-03-14", "", 8, 650),
    ("E002", "Operations", "Production Lead", "salary", 82000, "", "", "2023-01-09", "", 5, 650),
    ("E003", "Operations", "Production Technician", "hourly", "", 27.5, 40, "2023-06-05", "", 0, 520),
    ("E004", "Operations", "Production Technician", "hourly", "", 26.0, 40, "2024-02-12", "", 0, 520),
    ("E005", "Operations", "Production Technician", "hourly", "", 24.5, 40, "2025-05-19", "", 0, 520),
    ("E006", "Operations", "Logistics Coordinator", "salary", 64000, "", "", "2024-09-03", "", 3, 600),
    ("E007", "Sales", "Sales Director", "salary", 135000, "", "", "2021-08-23", "", 15, 700),
    ("E008", "Sales", "Account Executive", "salary", 88000, "", "", "2024-04-01", "", 12, 650),
    ("E009", "Sales", "Account Executive", "salary", 84000, "", "", "2026-01-12", "", 12, 650),
    ("E010", "Finance & Admin", "Controller", "salary", 118000, "", "", "2022-10-03", "", 8, 700),
    ("E011", "Finance & Admin", "AR/AP Specialist", "salary", 62000, "", "", "2025-02-17", "", 0, 560),
    ("E012", "Finance & Admin", "Office Coordinator", "salary", 48000, "", "", "2024-07-08", "2026-01-31", 0, 480),
    ("E013", "Product & Engineering", "Engineering Lead", "salary", 128000, "", "", "2022-05-16", "", 10, 700),
    ("E014", "Product & Engineering", "Software Engineer", "salary", 106000, "", "", "2025-03-10", "", 6, 650),
    # planned hires (after the forecast start date)
    ("E015", "Operations", "Production Technician (planned)", "hourly", "", 25.0, 40, "2026-07-06", "", 0, 520),
    ("E016", "Sales", "Account Executive (planned)", "salary", 90000, "", "", "2026-10-05", "", 12, 650),
]

if __name__ == "__main__":
    path = Path(__file__).with_name("neuraflow_payroll.csv")
    with path.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(HEADER)
        w.writerows(ROWS)
    print(f"wrote {len(ROWS)} employees to {path}")
