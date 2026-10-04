"""In-memory data store and the logical clock.

The store starts empty on every boot: nothing here seeds, preloads, or
registers any entity. The logical clock starts at exactly
2026-09-01T00:00:00Z and never falls back to wall-clock time.
"""

import threading
import uuid
from datetime import datetime, timezone


# Serializes request handling so cascades stay atomic under threaded Flask.
REQUEST_LOCK = threading.RLock()

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

stores = {
    "universities": {},
    "students": {},
    "employers": {},
    "employer_approvals": {},
    "job_postings": {},
    "career_events": {},
    "event_sessions": {},
    "event_signups": {},
    "applications": {},
    "interviews": {},
    "outreach_messages": {},
}

_clock = {"current": DEFAULT_CLOCK}
_seq = {"n": 0}


def now():
    return _clock["current"]


def wall_now():
    """System-managed timestamps (created_at/updated_at, PRD section 2.4) are
    stamped from the real clock; only the business timestamps enumerated in
    PRD section 2.5 read the logical clock."""
    return datetime.now(timezone.utc)


def set_clock(dt):
    _clock["current"] = dt


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def insert(kind, record):
    record["_seq"] = next_seq()
    stores[kind][record["id"]] = record
    return record


def get(kind, record_id):
    if record_id is None:
        return None
    return stores[kind].get(record_id)


def all_of(kind):
    return list(stores[kind].values())


def touch(record):
    """Every mutation refreshes updated_at and bumps version by 1."""
    record["updated_at"] = wall_now()
    record["version"] += 1
