"""In-memory data store, the logical plant clock and audit-field helpers.

Storage is process-local dictionaries keyed by id.  Nothing is persisted and
nothing is seeded: every row a test needs is built through the declared API.
"""

import datetime
import itertools
import uuid
from decimal import Decimal

# PRD 2.5 — the logical UTC clock starts at exactly 2026-08-01T00:00:00Z and
# never falls back to the host's wall clock.
CLOCK_DEFAULT = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=datetime.timezone.utc)

_seq = itertools.count(1)


class Store(object):
    def __init__(self):
        self.designs = {}
        self.standards = {}
        self.distributors = {}
        self.orders = {}
        self.work_orders = {}
        self.stator_builds = {}
        self.rotor_builds = {}
        self.assembly_records = {}
        self.performance_tests = {}
        self.nameplates = {}
        self.warranty_claims = {}
        self.ovens = {}
        self.test_cells = {}
        self.clock = CLOCK_DEFAULT


db = Store()


def now():
    """The logical clock instant."""
    return db.clock


def new_id():
    """PRD 2.4 — a UUID with no type prefix of any kind."""
    return str(uuid.uuid4())


def next_seq():
    return next(_seq)


def iso3(dt):
    """ISO 8601 UTC instant with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(datetime.timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def wall_iso3():
    return iso3(datetime.datetime.now(datetime.timezone.utc))


def base_row(mutable=True):
    """PRD 2.4 — server-minted id, created_at, and (for mutable rows)
    updated_at plus a version that starts at 1."""
    instant = now()
    row = {
        "id": new_id(),
        "created_at": instant,
    }
    if mutable:
        row["updated_at"] = instant
        row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    """PRD 2.4 — every mutation, including one suffered as a consequence of
    another resource's transition, refreshes updated_at and advances version."""
    if row is None:
        return
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = now()


def sort_key(row):
    """Default collection ordering: created_at ascending, registration order
    breaking ties."""
    return (row["created_at"], row["_seq"])


def by_created_at(rows):
    return sorted(rows, key=sort_key)


def public(row):
    """Strip internal bookkeeping keys from a row before serialisation."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def to_json(value):
    """Recursively convert stored values into JSON-ready values."""
    if isinstance(value, dict):
        return {k: to_json(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [to_json(v) for v in value]
    if isinstance(value, datetime.datetime):
        return iso3(value)
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    return value
