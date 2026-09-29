"""In-memory data store, identifier / timestamp minting and the logical clock.

The store starts completely empty on every boot: no entity is seeded, preloaded
or hardcoded anywhere in this module or at import time.
"""

import datetime as _dt
import itertools
import random
import string
import threading
import uuid

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

_lock = threading.RLock()
_seq = itertools.count(1)

# Collections keyed by id. Every one of them starts empty.
members = {}
vendors = {}
products = {}
trials = {}
feedback_entries = {}
negotiations = {}
subscriptions = {}
commitments = {}
auth_configs = {}
access_incidents = {}
usage_reports = {}
renewal_decisions = {}
archival_checks = {}

_clock = {"value": None}


# --------------------------------------------------------------------------- #
# time helpers
# --------------------------------------------------------------------------- #
def _fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    """Wall-clock ISO 8601 UTC with exactly three fractional digits."""
    return _fmt(_dt.datetime.now(_dt.timezone.utc))


def parse_instant(text):
    """Parse an ISO 8601 instant into an aware datetime, or return None."""
    if not isinstance(text, str) or not text.strip():
        return None
    raw = text.strip()
    if raw.endswith("Z") or raw.endswith("z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = _dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_dt.timezone.utc)
    return dt.astimezone(_dt.timezone.utc)


def clock_dt():
    with _lock:
        if _clock["value"] is None:
            _clock["value"] = parse_instant(DEFAULT_CLOCK_UTC)
        return _clock["value"]


def clock_iso():
    return _fmt(clock_dt())


def clock_date():
    """The calendar date of the logical clock's UTC value, as YYYY-MM-DD."""
    return clock_dt().strftime("%Y-%m-%d")


def clock_month():
    return clock_dt().strftime("%Y-%m")


def set_clock(dt):
    with _lock:
        _clock["value"] = dt


def reset():
    """Wipe every collection and the clock (used by nothing but kept explicit)."""
    with _lock:
        for coll in (
            members, vendors, products, trials, feedback_entries, negotiations,
            subscriptions, commitments, auth_configs, access_incidents,
            usage_reports, renewal_decisions, archival_checks,
        ):
            coll.clear()
        _clock["value"] = None


# --------------------------------------------------------------------------- #
# identity / row helpers
# --------------------------------------------------------------------------- #
def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def new_row(fields, versioned=True):
    """Build a row with server-minted identity and system fields."""
    row = {"id": new_id()}
    row.update(fields)
    stamp = now_iso()
    row["created_at"] = stamp
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = next(_seq)
    return row


def touch(row):
    """Refresh updated_at and bump version on a mutated row."""
    if "version" in row:
        row["version"] = row["version"] + 1
        row["updated_at"] = now_iso()


def mutate(row, changes):
    """Apply only the changes that actually differ; bump the row when they do."""
    changed = False
    for key, value in changes.items():
        if key not in row or row[key] != value or _type_differs(row.get(key), value):
            row[key] = value
            changed = True
    if changed:
        touch(row)
    return changed


def _type_differs(old, new):
    return isinstance(old, bool) != isinstance(new, bool)


def serialize(row):
    """Public representation: every key except the internal underscore ones."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def sort_rows(rows):
    """Default list ordering: created_at ascending, stable on insertion order."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
