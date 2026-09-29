"""Purely in-memory data store.

Nothing is seeded, preloaded or persisted: every dict below starts empty on
every boot, so re-invoking start.sh wipes all state.
"""

import threading
import uuid
from datetime import date, datetime, timezone

# ---------------------------------------------------------------------------
# collections
# ---------------------------------------------------------------------------
programs = {}
objectives = {}
nursery_blocks = {}
crossing_blocks = {}
lines = {}
plantings = {}
sites = {}
series = {}
entries = {}
observations = {}
analyses = {}
decisions = {}
agreements = {}
lots = {}
projects = {}

_lock = threading.Lock()
_seq = [0]

# ---------------------------------------------------------------------------
# logical clock (PRD 2.5): before it is ever set it reads exactly
# 2026-08-01T00:00:00Z and never falls back to real system time.
# ---------------------------------------------------------------------------
_clock = [datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)]


def clock_now():
    return _clock[0]


def clock_date():
    return _clock[0].date()


def set_clock(dt):
    _clock[0] = dt


def next_seq():
    with _lock:
        _seq[0] += 1
        return _seq[0]


def new_id():
    return str(uuid.uuid4())


def instant_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_instant(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def fmt_date(d):
    if isinstance(d, (date, datetime)):
        return d.strftime("%Y-%m-%d")
    return d


def new_record(versioned=True):
    """Common fields (PRD 2.4). PhenotypeObservation passes versioned=False."""
    rec = {"id": new_id()}
    rec["_seq"] = next_seq()
    rec["created_at"] = instant_now()
    if versioned:
        rec["updated_at"] = rec["created_at"]
        rec["version"] = 1
    return rec


def ordered(collection_or_iter):
    """Default ordering: created_at ascending (insertion sequence breaks ties)."""
    items = collection_or_iter.values() if isinstance(collection_or_iter, dict) else collection_or_iter
    return sorted(items, key=lambda r: (r["created_at"], r["_seq"]))
