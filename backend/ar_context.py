import csv
from pathlib import Path

DATA_FILE = Path(__file__).parent / "cdm_model" / "data" / "invoices.csv"


def get_ar_context(customer_id: str):
    invoices = []
    total_open_amount = 0.0

    with open(DATA_FILE, newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            if row["CustomerID"] == str(customer_id):
                amount = float(row["InvoiceAmount"])
                invoices.append(
                    {
                        "invoice_id": row["InvoiceID"],
                        "invoice_date": row["InvoiceDate"],
                        "due_date": row["DueDate"],
                        "invoice_amount": amount,
                    }
                )
                total_open_amount += amount

    if not invoices:
        return None

    return {
        "customer_id": str(customer_id),
        "invoice_count": len(invoices),
        "total_open_amount": total_open_amount,
        "invoices": invoices,
    }