"""In-memory data store. All state lives in process memory only.

The store starts empty on every boot — nothing is seeded, preloaded, or
persisted anywhere. The logical clock starts at 2026-09-01T00:00:00Z.
"""
from datetime import datetime, timezone

CLOCK_DEFAULT = datetime(2026, 9, 1, tzinfo=timezone.utc)

# entity tables keyed by id
markets = {}
drivers = {}
programs = {}
rides = {}
enrollments = {}
settlements = {}
statements = {}
appeals = {}
fraud_flags = {}
shortfalls = {}
forecasts = {}

# driver rolling rate events: driver_id -> list of event dicts (in insertion order)
rate_events = {}

# logical clock state
_clock_now = CLOCK_DEFAULT


def now():
    return _clock_now


def set_clock(dt):
    global _clock_now
    _clock_now = dt
