import csv
from pathlib import Path
from datetime import datetime, timedelta
from collections import defaultdict
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor

DATA_FILE = Path(__file__).parent / "cdm_model" / "data" / "invoices.csv"


def parse_date(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").date()


def build_training_data():
    customer_map = defaultdict(list)

    with open(DATA_FILE, newline="") as csvfile:
        reader = csv.DictReader(csvfile)
        for row in reader:
            customer_map[row["CustomerID"]].append(row)

    X_class = []
    y_class = []

    X_reg = []
    y_reg = []

    today = datetime.today().date()

    for customer_id, invoices in customer_map.items():
        invoice_count = len(invoices)
        total_amount = sum(float(i["InvoiceAmount"]) for i in invoices)
        avg_amount = total_amount / invoice_count if invoice_count else 0

        overdue_count = 0
        max_days_overdue = 0
        avg_days_past_due = 0
        due_day_values = []

        for inv in invoices:
            due_date = parse_date(inv["DueDate"])
            invoice_date = parse_date(inv["InvoiceDate"])

            due_day_values.append((due_date - invoice_date).days)

            days_overdue = (today - due_date).days
            if days_overdue > 0:
                overdue_count += 1
                avg_days_past_due += days_overdue
                if days_overdue > max_days_overdue:
                    max_days_overdue = days_overdue

        overdue_ratio = overdue_count / invoice_count if invoice_count else 0
        avg_days_past_due = avg_days_past_due / overdue_count if overdue_count else 0
        avg_terms_days = sum(due_day_values) / len(due_day_values) if due_day_values else 30

        features = [
            invoice_count,
            total_amount,
            avg_amount,
            overdue_count,
            overdue_ratio,
            max_days_overdue,
            avg_days_past_due,
            avg_terms_days,
        ]

        # classification label: risky or not
        risky = 1 if overdue_ratio > 0.5 or max_days_overdue > 60 else 0
        X_class.append(features)
        y_class.append(risky)

        # proxy payment timing label:
        # estimates days-to-pay based on terms plus lateness behavior
        proxy_days_to_pay = avg_terms_days + avg_days_past_due
        if proxy_days_to_pay < 0:
            proxy_days_to_pay = avg_terms_days

        X_reg.append(features)
        y_reg.append(proxy_days_to_pay)

    # ensure at least 2 classes for tiny demo datasets
    if len(set(y_class)) == 1 and len(y_class) > 0:
        if y_class[0] == 1:
            X_class.append([1, 100.0, 100.0, 0, 0.0, 0, 0.0, 30])
            y_class.append(0)
            X_reg.append([1, 100.0, 100.0, 0, 0.0, 0, 0.0, 30])
            y_reg.append(30)
        else:
            X_class.append([10, 50000.0, 5000.0, 10, 1.0, 120, 75.0, 30])
            y_class.append(1)
            X_reg.append([10, 50000.0, 5000.0, 10, 1.0, 120, 75.0, 30])
            y_reg.append(105)

    return X_class, y_class, X_reg, y_reg


def train_models():
    X_class, y_class, X_reg, y_reg = build_training_data()

    clf = RandomForestClassifier(n_estimators=50, random_state=42)
    clf.fit(X_class, y_class)

    reg = RandomForestRegressor(n_estimators=50, random_state=42)
    reg.fit(X_reg, y_reg)

    return clf, reg


CLASSIFIER_MODEL, REGRESSOR_MODEL = train_models()


def predict_customer_risk(customer_summary):
    invoice_count = customer_summary.get("invoice_count", 0)
    total_amount = customer_summary.get("total_amount", 0.0)
    avg_amount = total_amount / invoice_count if invoice_count else 0
    overdue_amount = customer_summary.get("overdue_amount", 0.0)
    overdue_ratio = overdue_amount / total_amount if total_amount else 0.0

    oldest_invoice_date = customer_summary.get("oldest_invoice_date")
    latest_due_date = customer_summary.get("latest_due_date")

    max_days_overdue = 0
    avg_days_past_due = 0

    today = datetime.today().date()

    if latest_due_date:
        latest_due = parse_date(latest_due_date)
        avg_days_past_due = max((today - latest_due).days, 0)

    if oldest_invoice_date:
        oldest_date = parse_date(oldest_invoice_date)
        max_days_overdue = max((today - oldest_date).days, 0)

    overdue_count_estimate = int(round(overdue_ratio * invoice_count))

    # if both dates exist, use them to approximate terms
    avg_terms_days = 30
    if oldest_invoice_date and latest_due_date:
        oldest_date = parse_date(oldest_invoice_date)
        latest_due = parse_date(latest_due_date)
        approx_terms = (latest_due - oldest_date).days
        if approx_terms > 0:
            avg_terms_days = approx_terms

    features = [[
        invoice_count,
        total_amount,
        avg_amount,
        overdue_count_estimate,
        overdue_ratio,
        max_days_overdue,
        avg_days_past_due,
        avg_terms_days,
    ]]

    prediction = CLASSIFIER_MODEL.predict(features)[0]

    probabilities = CLASSIFIER_MODEL.predict_proba(features)[0]
    classes = list(CLASSIFIER_MODEL.classes_)

    if 1 in classes:
        risky_index = classes.index(1)
        probability = float(probabilities[risky_index])
    else:
        probability = 1.0 if prediction == 1 else 0.0

    predicted_days_to_pay = float(REGRESSOR_MODEL.predict(features)[0])
    if predicted_days_to_pay < 0:
        predicted_days_to_pay = avg_terms_days

    predicted_days_to_pay = round(predicted_days_to_pay, 1)

    predicted_payment_date = None
    if oldest_invoice_date:
        base_date = parse_date(oldest_invoice_date)
        predicted_payment_date = (base_date + timedelta(days=predicted_days_to_pay)).isoformat()
    elif latest_due_date:
        base_date = parse_date(latest_due_date)
        predicted_payment_date = (base_date + timedelta(days=max(predicted_days_to_pay - avg_terms_days, 0))).isoformat()

    return {
        "ml_risk_prediction": "high" if prediction == 1 else "low",
        "ml_risk_probability": round(probability, 4),
        "predicted_days_to_pay": predicted_days_to_pay,
        "predicted_payment_date": predicted_payment_date,
    }