"""In-memory data store. Nothing is persisted, nothing is seeded at startup.

The store starts empty on every boot: every entity a test needs is created
through the declared API surface. `start.sh` re-invocation therefore wipes
every byte of state, as the per-test-server harness requires.
"""

from datetime import datetime, timezone

from util import iso, new_id, parse_dt

# The logical clock's fixed startup instant. It never falls back to wall time.
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

REGIONS = {}
DISTRICTS = {}
SCHOOLS = {}
APPLICANTS = {}
APPLICATIONS = {}
PATHWAYS = {}
MEMBERS = {}
PLACEMENTS = {}
MILESTONES = {}
SUPPORT_RECORDS = {}

CLOCK = {"now": DEFAULT_CLOCK}


def now():
    return CLOCK["now"]


def set_clock(dt):
    CLOCK["now"] = dt


def clock_iso():
    return iso(CLOCK["now"])


def stamp(record):
    """Attach the system-managed common fields to a freshly created record."""
    ts = clock_iso()
    record["id"] = new_id()
    record["created_at"] = ts
    record["updated_at"] = ts
    record["version"] = 1
    return record


def touch(record):
    """A mutation: refresh updated_at and increment version by exactly 1."""
    record["updated_at"] = clock_iso()
    record["version"] = record["version"] + 1
    return record


def put(table, record):
    table[record["id"]] = record
    return record


def parse_clock(value):
    return parse_dt(value)
