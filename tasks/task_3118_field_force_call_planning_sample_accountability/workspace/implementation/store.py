"""In-memory data store and logical clock for the Field Force Sample Accountability API.

The store starts completely empty on every boot. Nothing is seeded here.
"""

import datetime as dt

# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
_DEFAULT_CLOCK = dt.datetime(2026, 9, 1, 0, 0, 0, tzinfo=dt.timezone.utc)
_clock = _DEFAULT_CLOCK


def now():
    return _clock


def set_clock(new_dt):
    global _clock
    _clock = new_dt


# ---------------------------------------------------------------------------
# Entity collections (each maps id -> dict)
# ---------------------------------------------------------------------------
regions = {}
territories = {}
representatives = {}
prescribers = {}
products = {}
sample_lots = {}
lot_balances = {}
target_entries = {}
call_plans = {}
call_visits = {}
disbursements = {}
transfers = {}
count_sessions = {}
count_lines = {}
excursions = {}
sample_returns = {}

# Server-minted destruction report sequence
_dest_seq = 0


def next_destruction_ref():
    global _dest_seq
    _dest_seq += 1
    return "DEST-%04d" % _dest_seq
