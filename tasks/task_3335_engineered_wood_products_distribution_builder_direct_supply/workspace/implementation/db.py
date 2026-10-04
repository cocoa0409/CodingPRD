"""In-memory data store + logical clock."""
from datetime import datetime, timezone

# Logical clock — starts at exactly 2026-09-01T00:00:00Z, never wall clock
_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


def clock_now():
    return _clock


def clock_set(dt):
    global _clock
    _clock = dt


# In-memory stores — start empty on every boot
mill_capacity_weeks = {}   # id -> dict
products = {}              # id -> dict
price_index_entries = {}   # id -> dict
branches = {}              # id -> dict
inventory_lots = {}        # id -> dict
builders = {}              # id -> dict
jobs = {}                  # id -> dict
takeoff_requests = {}      # id -> dict
sales_orders = {}          # id -> dict
deliveries = {}            # id -> dict
truck_shifts = {}          # id -> dict
lien_filings = {}          # id -> dict
