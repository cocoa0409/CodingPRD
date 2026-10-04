"""In-memory data store and logical clock. No seeding: all dicts start empty."""
from datetime import datetime, timezone

COLLECTIONS = (
    "seasons", "vendors", "zones", "lots", "lot_lines", "warehouses",
    "holds", "stores", "plans", "store_skus", "tickets", "receipts",
    "receipt_lines", "shrink_cases", "markdown_events", "liquidation_orders",
)

db = {name: {} for name in COLLECTIONS}

_clock_state = {"current": datetime(2026, 9, 1, tzinfo=timezone.utc)}


def now():
    return _clock_state["current"]


def set_clock(dt):
    _clock_state["current"] = dt


def today_date():
    return now().date()
