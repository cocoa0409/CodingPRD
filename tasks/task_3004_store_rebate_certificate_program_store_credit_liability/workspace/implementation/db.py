"""In-memory data store.

Storage is process-local Python dictionaries keyed by entity id.  The store is
EMPTY on every boot: nothing is seeded, preloaded or hardcoded.  Every entity
is created exclusively through the declared HTTP surface.
"""

import itertools
import uuid
from datetime import datetime, timezone

from response import iso_timestamp

# ---------------------------------------------------------------------------
# Collections (all empty at import time -- never seeded)
# ---------------------------------------------------------------------------
stores = {}
programs = {}
program_items = {}
accounts = {}
jobs = {}
receipts = {}
receipt_lines = {}
returns = {}
submissions = {}
submission_lines = {}
certificates = {}
ledger_entries = {}
flags = {}
breakage_runs = {}

_seq = itertools.count(1)

# ---------------------------------------------------------------------------
# Server-side logical clock (PRD 2.6).  Fixed startup default:
# 2026-09-01T00:00:00Z.  Never the host wall clock.
# ---------------------------------------------------------------------------
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"current_utc": DEFAULT_CLOCK}


def clock_now():
    return _clock["current_utc"]


def set_clock(dt):
    _clock["current_utc"] = dt


def logical_timestamp():
    """Logical-clock instant rendered as an ISO 8601 UTC string (3 ms digits)."""
    return iso_timestamp(clock_now())


# ---------------------------------------------------------------------------
# Identity / system field helpers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def base_record(versioned=True):
    """id + created_at (+ updated_at/version when the entity carries them).

    PRD 2.4: version starts at 1 on creation and increments by exactly 1 on
    every mutation.  ReceiptLine / SubmissionLine / CreditLedgerEntry are the
    exceptions and carry only id + created_at.
    """
    stamp = iso_timestamp()
    rec = {"id": new_id(), "_seq": next_seq(), "created_at": stamp}
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    return rec


def touch(rec):
    """Bump version + updated_at for a write that changed a stored field."""
    rec["version"] = rec.get("version", 1) + 1
    rec["updated_at"] = iso_timestamp()


# ---------------------------------------------------------------------------
# Ordered access.  created_at ASC is the default list order (PRD 2.3); `_seq`
# is the monotonic insertion tiebreaker (never the id).
# ---------------------------------------------------------------------------
def ordered(collection):
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))


def sort_key(rec):
    return (rec["created_at"], rec["_seq"])
