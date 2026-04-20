from datetime import datetime, timedelta
import math


def _parse_date(date_str):
    try:
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except Exception:
        return None


def _clamp(value, min_value=0.0, max_value=1.0):
    return max(min_value, min(max_value, value))


def analyze_customer_summaries(customer_summaries):
    results = []

    # First pass: compute raw customer-level metrics
    for c in customer_summaries:
        total = float(c.get("total_amount", 0) or 0)
        overdue = float(c.get("overdue_amount", 0) or 0)
        invoices = c.get("invoice_details", []) or []

        invoice_count = int(c.get("invoice_count", 0) or 0)
        overdue_ratio = overdue / total if total else 0.0

        days_late_list = []
        current_invoices = 0
        terms_days_list = []
        invoice_amounts = []

        today = datetime.today().date()

        for inv in invoices:
            amount = float(inv.get("invoice_amount", 0) or 0)
            invoice_amounts.append(amount)

            inv_date = _parse_date(inv.get("invoice_date"))
            due = _parse_date(inv.get("due_date"))

            if inv_date and due:
                terms_days = (due - inv_date).days
                if terms_days >= 0:
                    terms_days_list.append(terms_days)

            if due:
                days = (today - due).days
                if days > 0:
                    days_late_list.append(days)
                else:
                    current_invoices += 1

        avg_days_late = sum(days_late_list) / len(days_late_list) if days_late_list else 0.0
        max_days_late = max(days_late_list) if days_late_list else 0.0
        overdue_invoice_ratio = (len(days_late_list) / invoice_count) if invoice_count else 0.0
        avg_invoice_amount = (sum(invoice_amounts) / len(invoice_amounts)) if invoice_amounts else 0.0
        avg_terms_days = (sum(terms_days_list) / len(terms_days_list)) if terms_days_list else 30.0
        largest_invoice_ratio = (max(invoice_amounts) / total) if invoice_amounts and total else 0.0

        c["overdue_ratio"] = overdue_ratio
        c["avg_days_late"] = avg_days_late
        c["max_days_late"] = max_days_late
        c["overdue_invoice_ratio"] = overdue_invoice_ratio
        c["avg_invoice_amount"] = round(avg_invoice_amount, 2)
        c["avg_terms_days"] = round(avg_terms_days, 1)
        c["largest_invoice_ratio"] = round(largest_invoice_ratio, 4)

        results.append(c)

    # Normalize across portfolio population
    max_overdue = max((c["overdue_ratio"] for c in results), default=1)
    max_avg_late = max((c["avg_days_late"] for c in results), default=1)
    max_max_late = max((c["max_days_late"] for c in results), default=1)
    max_invoice_concentration = max((c["largest_invoice_ratio"] for c in results), default=1)

    for c in results:
        score = 0.0

        score += (c["overdue_ratio"] / max_overdue) * 0.35 if max_overdue else 0
        score += (c["avg_days_late"] / max_avg_late) * 0.25 if max_avg_late else 0
        score += (c["max_days_late"] / max_max_late) * 0.15 if max_max_late else 0
        score += c["overdue_invoice_ratio"] * 0.15
        score += (c["largest_invoice_ratio"] / max_invoice_concentration) * 0.10 if max_invoice_concentration else 0

        # Reward good behavior
        if c["overdue_ratio"] < 0.10:
            score -= 0.10
        if c["avg_days_late"] < 5:
            score -= 0.10
        if c["overdue_invoice_ratio"] < 0.15:
            score -= 0.05

        score = _clamp(score, 0.0, 1.0)

        c["ml_risk_probability"] = round(score, 3)

        if score > 0.70:
            c["ml_risk_prediction"] = "high"
        elif score > 0.40:
            c["ml_risk_prediction"] = "medium"
        else:
            c["ml_risk_prediction"] = "low"

        # predicted days to pay
        # customer-specific proxy using terms + lateness behavior
        predicted_days_to_pay = c["avg_terms_days"] + c["avg_days_late"]
        if predicted_days_to_pay < 0:
            predicted_days_to_pay = c["avg_terms_days"]

        c["predicted_days_to_pay"] = round(predicted_days_to_pay, 1)

        # predicted payment date
        latest_due_date = _parse_date(c.get("latest_due_date"))
        oldest_invoice_date = _parse_date(c.get("oldest_invoice_date"))

        predicted_payment_date = None
        if latest_due_date:
            if c["avg_days_late"] > 0:
                predicted_payment_date = (latest_due_date + timedelta(days=c["avg_days_late"])).isoformat()
            else:
                predicted_payment_date = latest_due_date.isoformat()
        elif oldest_invoice_date:
            predicted_payment_date = (
                oldest_invoice_date + timedelta(days=predicted_days_to_pay)
            ).isoformat()

        c["predicted_payment_date"] = predicted_payment_date

        c["behavior_summary"] = (
            f"Customer analyzed relative to portfolio peers: "
            f"{round(c['overdue_ratio'] * 100, 1)}% overdue by amount, "
            f"{round(c['overdue_invoice_ratio'] * 100, 1)}% overdue by invoice count, "
            f"avg {round(c['avg_days_late'], 1)} days late, max {round(c['max_days_late'], 1)} days late."
        )

    return sorted(results, key=lambda x: x["ml_risk_probability"], reverse=True)