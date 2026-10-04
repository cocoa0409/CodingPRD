"""In-memory data store for the EAF mini-mill API.

All state lives in module-level dicts keyed by id. A fresh process starts
with a completely empty store; nothing is seeded.
"""
import copy
from datetime import datetime, timezone

# --- entity stores -------------------------------------------------------
mills = {}
surcharge_indices = {}
contracts = {}
scrap_lots = {}
grades = {}
heats = {}
charge_lines = {}
meltdown_sheets = {}
campaigns = {}
campaign_lines = {}
accounts = {}
orders = {}
mtrs = {}
windows = {}
events = {}
waivers = {}
intervals = {}
scorecards = {}

# per-mill MTR sequence counters: mill_id -> int
mtr_sequences = {}

# --- logical clock --------------------------------------------------------
_CLOCK_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = _CLOCK_DEFAULT


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


def now_iso():
    """Wall-clock timestamp for created_at/updated_at (ISO8601 UTC, 3 frac digits)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{datetime.now(timezone.utc).microsecond // 1000:03d}Z"


def wall_now():
    return datetime.now(timezone.utc)


def ts_now():
    n = wall_now()
    return n.strftime("%Y-%m-%dT%H:%M:%S.") + f"{n.microsecond // 1000:03d}Z"
