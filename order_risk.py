"""SweaterCo's order-risk dashboard. Run with `uv run streamlit run app.py`."""

from datetime import date, timedelta
from pathlib import Path

import pandas as pd


TODAY = date(2026, 4, 1)
ORDERS_PATH = Path(__file__).resolve().parent / "track1" / "data" / "orders.csv"
RISK_LEVELS = ["Overdue", "At risk", "No flag"]
STAGES = ["KNITTING", "ASSEMBLY", "WASHING", "PACKING"]
DATE_COLUMNS = ["order_date", "due_date", "last_activity_date", "completed_date"]
REQUIRED_COLUMNS = {
    "order_id", "customer", "product", "category", "pieces", "status",
    "current_stage", "days_late", *DATE_COLUMNS,
}


def load_orders(path: Path) -> pd.DataFrame:
    orders = pd.read_csv(path)
    missing = REQUIRED_COLUMNS - set(orders.columns)
    if missing:
        raise ValueError(f"Missing columns: {', '.join(sorted(missing))}.")
    for column in DATE_COLUMNS:
        orders[column] = pd.to_datetime(orders[column], format="%Y-%m-%d", errors="raise")
    required_values = sorted(REQUIRED_COLUMNS - {"completed_date", "days_late"})
    if orders[required_values].isna().any().any():
        raise ValueError("Required order details or dates are blank.")
    orders["pieces"] = pd.to_numeric(orders["pieces"], errors="raise")
    if ((orders["pieces"] <= 0) | (orders["pieces"] % 1 != 0)).any():
        raise ValueError("Piece counts must be positive whole numbers.")
    if not orders["status"].isin(["COMPLETE", "IN_PROGRESS"]).all():
        raise ValueError("Order status must be COMPLETE or IN_PROGRESS.")
    active = orders["status"].eq("IN_PROGRESS")
    if not orders.loc[active, "current_stage"].isin(STAGES).all():
        raise ValueError("An unfinished order has an unknown production stage.")
    return orders


def working_days_since(last_activity: date, today: date) -> int:
    """Count Monday–Saturday days in (last_activity, today]."""
    return sum(
        (last_activity + timedelta(days=offset)).weekday() != 6
        for offset in range(1, (today - last_activity).days + 1)
    )


def assess_risk(due_date: date, last_activity: date, today: date = TODAY) -> tuple[str, str, int]:
    days_until_due = (due_date - today).days
    inactive_days = working_days_since(last_activity, today)
    reasons = []
    if days_until_due < 0:
        reasons.append(f"Overdue by {-days_until_due} calendar days")
    elif days_until_due <= 7:
        reasons.append("Due today" if days_until_due == 0 else f"Due in {days_until_due} calendar days")
    if inactive_days >= 3:
        reasons.append(f"No activity for {inactive_days} working days")
    risk = "Overdue" if days_until_due < 0 else "At risk" if reasons else "No flag"
    return risk, "; ".join(reasons) or "No warning rules triggered", inactive_days


def evaluate_orders(orders: pd.DataFrame, today: date = TODAY) -> pd.DataFrame:
    active = orders.loc[orders["status"].eq("IN_PROGRESS")].copy()
    assessments = [
        assess_risk(row.due_date.date(), row.last_activity_date.date(), today)
        for row in active.itertuples()
    ]
    for index, column in enumerate(["risk", "reasons", "inactive_working_days"]):
        active[column] = [assessment[index] for assessment in assessments]
    active["risk_rank"] = active["risk"].map({risk: rank for rank, risk in enumerate(RISK_LEVELS)})
    return active.sort_values(["risk_rank", "due_date", "order_id"])


