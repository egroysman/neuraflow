import csv
import io
import os
from datetime import datetime
from typing import Optional, Dict, Any
from .base import BaseDataSource
from ml_analytics import analyze_customer_summaries
from action_engine import apply_actions


class CSVDataSource(BaseDataSource):
    def __init__(self, default_csv_path: Optional[str] = None):
        self.default_csv_path = default_csv_path
        self.history_csv_path = os.getenv("CUSTOMER_HISTORY_CSV_PATH")

    def _safe_float(self, value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0

    def _parse_date(self, date_str):
        try:
            if not date_str:
                return None
            return datetime.strptime(str(date_str), "%Y-%m-%d").date()
        except (TypeError, ValueError):
            return None

    def _read_rows(self, uploaded_file_bytes: Optional[bytes] = None):
        if uploaded_file_bytes:
            text = uploaded_file_bytes.decode("utf-8")
            reader = csv.DictReader(io.StringIO(text))
            return list(reader)

        if self.default_csv_path:
            with open(self.default_csv_path, newline="") as csvfile:
                reader = csv.DictReader(csvfile)
                return list(reader)

        return []

    def _read_customer_history(self):
        history_map = {}

        if not self.history_csv_path or not os.path.exists(self.history_csv_path):
            return history_map

        with open(self.history_csv_path, newline="") as csvfile:
            reader = csv.DictReader(csvfile)
            for row in reader:
                customer_id = str(row.get("CustomerID", "")).strip()
                if not customer_id:
                    continue

                history_map[customer_id] = {
                    "Behavior": row.get("Behavior", ""),
                    "TotalInvoices": int(float(row.get("TotalInvoices", 0) or 0)),
                    "PaidInvoices": int(float(row.get("PaidInvoices", 0) or 0)),
                    "OpenInvoices": int(float(row.get("OpenInvoices", 0) or 0)),
                    "AvgDaysToPay": self._safe_float(row.get("AvgDaysToPay")),
                    "OnTimePaymentRate": self._safe_float(row.get("OnTimePaymentRate")),
                }

        return history_map

    def _estimate_30_day_collection(self, customer_summary, history_row):
        open_ar = float(customer_summary.get("total_amount", 0.0) or 0.0)
        overdue_amount = float(customer_summary.get("overdue_amount", 0.0) or 0.0)
        risk_prob = float(customer_summary.get("ml_risk_probability", 0.0) or 0.0)
        predicted_days_to_pay = float(customer_summary.get("predicted_days_to_pay", 0.0) or 0.0)

        on_time_rate = float(history_row.get("OnTimePaymentRate", 0.0) or 0.0)
        behavior = str(history_row.get("Behavior", "")).lower()

        if behavior == "good":
            behavior_factor = 0.92
        elif behavior == "late":
            behavior_factor = 0.35
        else:
            behavior_factor = 0.60

        timing_factor = 1.0
        if predicted_days_to_pay > 60:
            timing_factor = 0.30
        elif predicted_days_to_pay > 45:
            timing_factor = 0.55
        elif predicted_days_to_pay > 30:
            timing_factor = 0.78

        risk_factor = max(0.18, 1.0 - risk_prob)

        overdue_penalty = 1.0
        if open_ar > 0:
            overdue_ratio = overdue_amount / open_ar
            overdue_penalty = max(0.35, 1.0 - (overdue_ratio * 0.45))

        historical_collection_factor = max(
            0.10,
            min(0.98, (on_time_rate * 0.70) + (behavior_factor * 0.30))
        )

        predicted_collection_rate_next_30_days = max(
            0.03,
            min(
                0.98,
                historical_collection_factor * timing_factor * risk_factor * overdue_penalty
            )
        )

        predicted_amount_paid_next_30_days = round(
            open_ar * predicted_collection_rate_next_30_days, 2
        )

        return {
            "historical_on_time_payment_rate": round(on_time_rate, 4),
            "historical_behavior_band": behavior or "unknown",
            "predicted_collection_rate_next_30_days": round(predicted_collection_rate_next_30_days, 4),
            "predicted_amount_paid_next_30_days": predicted_amount_paid_next_30_days,
        }

    def get_customer_summaries(self, uploaded_file_bytes: Optional[bytes] = None) -> Dict[str, Any]:
        rows = self._read_rows(uploaded_file_bytes)

        if not rows:
            return {
                "row_count": 0,
                "columns": [],
                "sample_rows": [],
                "total_invoice_amount": 0.0,
                "customer_count": 0,
                "customer_summaries": [],
                "top_risky_customers": [],
                "top_recommended_actions": [],
                "aging_buckets": {},
                "portfolio_expected_cash_next_30_days": 0.0,
                "source_type": "csv",
            }

        history_map = self._read_customer_history()
        columns = list(rows[0].keys()) if rows else []
        sample_rows = rows[:5]
        today = datetime.today().date()

        total_amount = 0.0
        customer_map = {}
        aging_buckets = {
            "current": 0.0,
            "1_30_overdue": 0.0,
            "31_60_overdue": 0.0,
            "61_90_overdue": 0.0,
            "90_plus_overdue": 0.0,
        }

        for row in rows:
            customer_id = str(row.get("CustomerID", "")).strip()
            invoice_amount = self._safe_float(row.get("InvoiceAmount"))
            due_date = self._parse_date(row.get("DueDate"))
            invoice_date = self._parse_date(row.get("InvoiceDate"))
            payment_date = self._parse_date(row.get("PaymentDate"))
            paid_amount = self._safe_float(row.get("PaidAmount"))
            open_amount = self._safe_float(row.get("OpenAmount"))
            status = str(row.get("Status", "")).strip()
            dispute_flag = int(float(row.get("DisputeFlag", 0) or 0))
            partial_payment_flag = int(float(row.get("PartialPaymentFlag", 0) or 0))

            total_amount += invoice_amount

            if customer_id not in customer_map:
                customer_map[customer_id] = {
                    "customer_id": customer_id,
                    "invoice_count": 0,
                    "total_amount": 0.0,
                    "overdue_amount": 0.0,
                    "latest_due_date": None,
                    "oldest_invoice_date": None,
                    "invoice_details": [],
                }

            customer_map[customer_id]["invoice_count"] += 1
            customer_map[customer_id]["total_amount"] += invoice_amount

            customer_map[customer_id]["invoice_details"].append(
                {
                    "invoice_id": str(row.get("InvoiceID", "")).strip(),
                    "invoice_amount": invoice_amount,
                    "invoice_date": invoice_date.isoformat() if invoice_date else None,
                    "due_date": due_date.isoformat() if due_date else None,
                    "payment_date": payment_date.isoformat() if payment_date else None,
                    "paid_amount": round(paid_amount, 2),
                    "open_amount": round(open_amount, 2),
                    "status": status,
                    "dispute_flag": dispute_flag,
                    "partial_payment_flag": partial_payment_flag,
                }
            )

            if due_date:
                if (
                    customer_map[customer_id]["latest_due_date"] is None
                    or due_date.isoformat() > customer_map[customer_id]["latest_due_date"]
                ):
                    customer_map[customer_id]["latest_due_date"] = due_date.isoformat()

                # only open balance should contribute to overdue exposure
                days_overdue = (today - due_date).days

                if open_amount > 0:
                    if days_overdue <= 0:
                        aging_buckets["current"] += open_amount
                    elif 1 <= days_overdue <= 30:
                        aging_buckets["1_30_overdue"] += open_amount
                        customer_map[customer_id]["overdue_amount"] += open_amount
                    elif 31 <= days_overdue <= 60:
                        aging_buckets["31_60_overdue"] += open_amount
                        customer_map[customer_id]["overdue_amount"] += open_amount
                    elif 61 <= days_overdue <= 90:
                        aging_buckets["61_90_overdue"] += open_amount
                        customer_map[customer_id]["overdue_amount"] += open_amount
                    else:
                        aging_buckets["90_plus_overdue"] += open_amount
                        customer_map[customer_id]["overdue_amount"] += open_amount

            if invoice_date:
                if (
                    customer_map[customer_id]["oldest_invoice_date"] is None
                    or invoice_date.isoformat() < customer_map[customer_id]["oldest_invoice_date"]
                ):
                    customer_map[customer_id]["oldest_invoice_date"] = invoice_date.isoformat()

        customer_summaries = sorted(
            customer_map.values(),
            key=lambda x: x["total_amount"],
            reverse=True
        )

        customer_behavior_scored = analyze_customer_summaries(customer_summaries)
        action_customers = apply_actions(customer_behavior_scored)

        portfolio_expected_cash_next_30_days = 0.0
        enriched_customers = []

        for customer in action_customers:
            customer_id = str(customer.get("customer_id"))
            history_row = history_map.get(customer_id, {})
            cash_forecast = self._estimate_30_day_collection(customer, history_row)

            enriched = {
                **customer,
                **cash_forecast,
            }

            portfolio_expected_cash_next_30_days += enriched["predicted_amount_paid_next_30_days"]
            enriched_customers.append(enriched)

        top_customers_by_exposure = sorted(
            enriched_customers,
            key=lambda x: x["total_amount"],
            reverse=True
        )[:5]

        top_customers_by_overdue = sorted(
            enriched_customers,
            key=lambda x: x["overdue_amount"],
            reverse=True
        )[:5]

        top_risky_customers = sorted(
            enriched_customers,
            key=lambda x: x.get("ml_risk_probability", 0.0),
            reverse=True
        )[:5]

        top_recommended_actions = sorted(
            enriched_customers,
            key=lambda x: (
                {"critical": 4, "high": 3, "medium": 2, "low": 1}.get(x.get("action_priority", "low"), 1),
                x.get("ml_risk_probability", 0.0),
            ),
            reverse=True
        )[:5]

        top_expected_payers_next_30_days = sorted(
            enriched_customers,
            key=lambda x: x.get("predicted_amount_paid_next_30_days", 0.0),
            reverse=True
        )[:5]

        return {
            "row_count": len(rows),
            "columns": columns,
            "sample_rows": sample_rows,
            "total_invoice_amount": total_amount,
            "customer_count": len(enriched_customers),
            "aging_buckets": aging_buckets,
            "top_customers_by_exposure": top_customers_by_exposure,
            "top_customers_by_overdue": top_customers_by_overdue,
            "top_risky_customers": top_risky_customers,
            "top_recommended_actions": top_recommended_actions,
            "top_expected_payers_next_30_days": top_expected_payers_next_30_days,
            "portfolio_expected_cash_next_30_days": round(portfolio_expected_cash_next_30_days, 2),
            "customer_summaries": enriched_customers,
            "source_type": "csv",
        }

    def get_customer_detail(self, customer_id: str, uploaded_file_bytes: Optional[bytes] = None) -> Optional[Dict[str, Any]]:
        summary = self.get_customer_summaries(uploaded_file_bytes)
        for customer in summary.get("customer_summaries", []):
            if str(customer.get("customer_id")) == str(customer_id):
                return customer
        return None