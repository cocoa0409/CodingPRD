"""In-memory data store + logical clock.

Storage is dicts keyed by id (PRD-bench contract: in-memory only, no seeding).
The store starts completely empty on every boot; the logical clock starts at
exactly 2026-09-01T00:00:00Z (PRD §2.4).
"""
import uuid
from datetime import datetime, timezone

from core import fmt_dt, fmt_dt_sec  # noqa: F401  (re-exported for convenience)

CLOCK_DEFAULT = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.institutions = {}
        self.agreements = {}
        self.users = {}
        self.periods = {}
        self.students = {}
        self.directives = {}
        self.files = {}
        self.entries = {}
        self.cases = {}
        self.degrees = {}
        self.requesters = {}
        self.requests = {}
        self.notifications = {}
        self.datasets = {}
        self.seq = 0  # global monotonic insertion sequence (created_at tiebreak)
        self.current_utc = CLOCK_DEFAULT


store = Store()


def now():
    return store.current_utc


def next_seq():
    store.seq += 1
    return store.seq


def new_entity(fields):
    """Create a resource dict with common fields (PRD §2.5).

    version starts at 1; created_at/updated_at come from the logical clock.
    """
    t = now()
    e = {
        "id": str(uuid.uuid4()),
        "created_at": t,
        "updated_at": t,
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(fields)
    return e


def touch(e):
    """Every mutation refreshes updated_at and increments version (PRD §2.9)."""
    e["updated_at"] = now()
    e["version"] += 1


def serialize(e):
    out = {}
    for k, v in e.items():
        if k.startswith("_"):
            continue
        if isinstance(v, datetime):
            # PRD §2.5 pins three fractional digits for created_at/updated_at
            # only; every other instant renders in the PRD's own T00:00:00Z
            # notation (§2.4 clock default, §2.5 date-valued fields).
            out[k] = fmt_dt(v) if k in ("created_at", "updated_at") else fmt_dt_sec(v)
        else:
            out[k] = v
    return out


def sorted_created(items):
    """created_at ASC, with insertion order as the deterministic tiebreak."""
    return sorted(items, key=lambda e: (e["created_at"], e["_seq"]))
