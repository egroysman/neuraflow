def recommend_action(customer):
    risk_probability = customer.get("ml_risk_probability", 0.0)
    overdue_amount = customer.get("overdue_amount", 0.0)
    total_amount = customer.get("total_amount", 0.0)
    predicted_days_to_pay = customer.get("predicted_days_to_pay", 0.0)
    invoice_count = customer.get("invoice_count", 0)

    overdue_ratio = (overdue_amount / total_amount) if total_amount else 0.0

    if risk_probability >= 0.85 or overdue_ratio >= 0.60 or predicted_days_to_pay >= 90:
        return {
            "recommended_action": "Escalate immediately",
            "action_priority": "critical",
            "action_reason": "High predicted risk, significant overdue exposure, or very late expected payment."
        }

    if risk_probability >= 0.65 or overdue_ratio >= 0.35 or predicted_days_to_pay >= 60:
        return {
            "recommended_action": "Collections outreach",
            "action_priority": "high",
            "action_reason": "Elevated payment risk or meaningful overdue concentration."
        }

    if risk_probability >= 0.40 or overdue_ratio >= 0.15 or predicted_days_to_pay >= 45:
        return {
            "recommended_action": "Monitor closely",
            "action_priority": "medium",
            "action_reason": "Some risk signals exist, but not enough for escalation yet."
        }

    return {
        "recommended_action": "No immediate action",
        "action_priority": "low",
        "action_reason": "Current indicators suggest low short-term collection risk."
    }


def apply_actions(customer_summaries):
    results = []

    for customer in customer_summaries:
        action = recommend_action(customer)
        enriched = {
            **customer,
            **action
        }
        results.append(enriched)

    priority_order = {
        "critical": 4,
        "high": 3,
        "medium": 2,
        "low": 1
    }

    results.sort(
        key=lambda x: (
            priority_order.get(x.get("action_priority", "low"), 1),
            x.get("ml_risk_probability", 0.0),
            x.get("overdue_amount", 0.0)
        ),
        reverse=True
    )

    return results