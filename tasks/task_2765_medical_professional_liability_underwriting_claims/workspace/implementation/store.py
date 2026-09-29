"""In-memory store, record identity, the logical clock and the version unit of work.

Storage is process-local Python dicts only: every boot starts completely empty
and nothing is ever persisted outside the process.
"""
import random
import string
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from flask import g

import constants as C

_LOCK = threading.RLock()

TS_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def now_iso():
    """The logical UTC instant with three fractional digits (audit fields).

    PRD 2.6: "The server keeps a logical UTC clock rather than reading
    wall-clock time... it never falls back to real time." Every server-minted
    stamp -- created_at and updated_at included -- therefore reads the logical
    clock; ties in a single logical instant are broken by the insertion
    sequence wherever ordering matters.
    """
    return db.clock_dt.strftime(TS_FMT)[:-3] + "Z"


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


class Store(object):
    def __init__(self):
        self.specialty_classes = {}
        self.insureds = {}
        self.enrollments = {}
        self.peer_review_cases = {}
        self.policies = {}
        self.policy_terms = {}
        self.tail_endorsements = {}
        self.claims = {}
        self.reserve_entries = {}
        self.counsel_firms = {}
        self.counsel_assignments = {}
        self.negotiations = {}
        self.npdb_reports = {}
        self.rate_filings = {}
        # logical clock (PRD 2.6)
        self.clock_str = C.CLOCK_EPOCH_STR
        self.clock_dt = datetime(2026, 8, 1, 0, 0, 0)
        # monotonic insertion sequence and the two document-number sequences
        self._seq = 0
        self._policy_seq = 0
        self._filing_seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    def next_policy_number(self):
        self._policy_seq += 1
        return "MPL-%06d" % self._policy_seq

    def next_filing_number(self):
        self._filing_seq += 1
        return "RF-%06d" % self._filing_seq

    # --- logical clock -----------------------------------------------------
    def logical_now(self):
        """The logical instant, echoed exactly as the operator supplied it."""
        return self.clock_str

    def logical_date(self):
        return self.clock_dt.date()


db = Store()


def new_record(fields, versioned=True):
    """Mint a record with its common fields (PRD 2.4)."""
    stamp = now_iso()
    rec = {"id": str(uuid.uuid4()), "created_at": stamp}
    rec.update(fields)
    if versioned:
        rec["updated_at"] = stamp
        rec["version"] = 1
    rec["_seq"] = db.next_seq()
    fresh = getattr(g, "_fresh", None)
    if fresh is None:
        fresh = set()
        g._fresh = fresh
    fresh.add(id(rec))
    return rec


# --- version unit of work ---------------------------------------------------
def touch(rec):
    """Mark a record mutated: exactly one version bump per record per request."""
    if rec is None or "version" not in rec:
        return
    # A record minted by this same request already carries its final values at
    # version 1; cascade recomputation must not push it to version 2.
    if id(rec) in getattr(g, "_fresh", ()):
        return
    dirty = getattr(g, "_dirty", None)
    if dirty is None:
        dirty = {}
        g._dirty = dirty
    dirty[id(rec)] = rec


def flush():
    """Apply the pending version/updated_at bumps before the response is built."""
    dirty = getattr(g, "_dirty", None)
    if not dirty:
        return
    stamp = now_iso()
    for rec in dirty.values():
        rec["version"] = int(rec["version"]) + 1
        rec["updated_at"] = stamp
    g._dirty = {}


# --- ordering ---------------------------------------------------------------
def by_created(rec):
    return (rec["created_at"], rec["_seq"])


def sorted_records(records):
    return sorted(records, key=by_created)


def all_of(table):
    return sorted_records(list(table.values()))


# --- serialisation ----------------------------------------------------------
def to_json(value):
    if isinstance(value, dict):
        return {k: to_json(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    if isinstance(value, Decimal):
        return float(value)
    return value
