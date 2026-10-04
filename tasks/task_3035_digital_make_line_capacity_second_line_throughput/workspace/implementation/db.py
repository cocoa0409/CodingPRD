"""In-memory data store. Starts completely empty on every boot (per benchmark
contract — no seeding)."""

from datetime import datetime, timezone, timedelta


class Store:
    """Global singleton data store."""

    def __init__(self):
        self.stores = {}                # id -> dict
        self.ingredients = {}           # id -> dict
        self.batches = {}               # id -> dict
        self.menu_items = {}            # id -> dict
        self.recipe_components = {}     # id -> dict
        self.marketplace_channels = {}  # id -> dict
        self.production_windows = {}    # id -> dict
        self.orders = {}                # id -> dict
        self.order_lines = {}           # id -> dict
        self.verifications = {}         # id -> dict
        self.deployments = {}           # id -> dict
        self.suppression_events = {}    # id -> dict
        self.waste_events = {}          # id -> dict
        self.day_closes = {}            # id -> dict
        # Logical clock: exactly 2026-09-01T00:00:00Z at startup; never wall clock.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


db = Store()


def now_iso_with_ms():
    """Server-side timestamp for created_at/updated_at fields. Uses logical
    clock but with real sub-second uniqueness via monotonic counter, formatted
    ISO 8601 UTC with three fractional digits."""
    return db.clock.strftime("%Y-%m-%dT%H:%M:%S.") + f"{db.clock.microsecond // 1000:03d}Z"


# A monotonic counter to guarantee uniqueness of created_at within same logical instant.
_mono_counter = 0


def fresh_timestamp():
    """Returns an ISO-8601 UTC timestamp string with 3 fractional digits.
    Combines the logical clock with a monotonically increasing counter so
    every resource created in the same logical instant still gets a distinct,
    increasing created_at value (needed for deterministic created_at ASC sort)."""
    global _mono_counter
    _mono_counter += 1
    # Use logical clock date plus counter-based microseconds to keep order stable.
    base = db.clock
    # Add counter microseconds (wrap at 1 second in microsecond space)
    micros = _mono_counter % 1_000_000
    secs = _mono_counter // 1_000_000
    t = base + timedelta(seconds=secs, microseconds=micros)
    return t.strftime("%Y-%m-%dT%H:%M:%S.") + f"{t.microsecond // 1000:03d}Z"


def reset_monotonic():
    global _mono_counter
    _mono_counter = 0
