"""In-memory store.

Nothing is seeded: every collection below starts empty on every boot and is only
ever populated through the declared endpoints (the harness reboots the process
before each test, so a fresh empty store is the required initial condition).
"""
import itertools
import threading
import uuid

from util import parse_instant, fmt_instant

# PRD 2.4: the logical clock starts at this instant on every boot.
CLOCK_DEFAULT = "2026-08-01T00:00:00.000Z"

LOCK = threading.RLock()

# One dict per resource type, keyed by id, insertion-ordered.
cedents = {}
reinsurers = {}
programs = {}
exposure_submissions = {}
layers = {}
market_submissions = {}
quotes = {}
signing_lines = {}
contract_documents = {}
brokerage_disclosures = {}
fiduciary_transactions = {}
claim_advocacies = {}
cession_disputes = {}
renewal_reports = {}

_seq = itertools.count(1)
_clock = {"now": parse_instant(CLOCK_DEFAULT)}


def next_seq():
    return next(_seq)


def new_id():
    """PRD 2.5: an opaque UUID with no type prefix."""
    return str(uuid.uuid4())


def now():
    return _clock["now"]


def now_str():
    return fmt_instant(_clock["now"])


def set_now(instant):
    _clock["now"] = instant
    return _clock["now"]


def touch(row):
    """PRD 2.5 / 2.9: refresh updated_at and increment version by exactly one.

    Used both for direct writes and for every cascade-induced mutation.
    """
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = now()
    return row


def base_row(versioned=True):
    row = {"id": new_id(), "created_at": now(), "_seq": next_seq()}
    if versioned:
        row["updated_at"] = row["created_at"]
        row["version"] = 1
    return row


def ordered(collection):
    """PRD 2.7: created_at ascending, insertion sequence breaking ties."""
    return sorted(collection.values(), key=lambda r: (r["created_at"], r["_seq"]))
