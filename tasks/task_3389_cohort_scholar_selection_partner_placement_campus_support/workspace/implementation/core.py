"""In-memory store, logical clock, id/timestamp helpers, round-half-up.

Storage is in-memory dicts keyed by id (PRD benchmark: no persistence). The
store starts completely empty on every boot — nothing is seeded. All entity
timestamps derive from the logical clock (PRD 2.4: "all time-dependent
behavior in the system is driven by a logical clock, never by wall-clock
time"); offer expiry (= created_at + 14 days) is meaningless otherwise.
"""

import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

from constants import BOOT_ISO


def parse_iso(s):
    """Parse an ISO 8601 datetime string to an aware UTC datetime.

    Raises ValueError on unparseable input. Naive inputs are treated as UTC.
    """
    t = s.strip()
    if t.endswith(("Z", "z")):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits, e.g. 2026-09-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def rhu(numerator, denominator):
    """Round-half-up integer division (PRD 2.8)."""
    return int(
        (Decimal(int(numerator)) / Decimal(int(denominator))).quantize(
            Decimal("1"), rounding=ROUND_HALF_UP
        )
    )


class Store:
    def __init__(self):
        self.clock = parse_iso(BOOT_ISO)
        self.seq = 0  # monotonic insertion counter: created_at ASC tie-break
        self.city_programs = {}
        self.partners = {}
        self.nominees = {}
        self.evaluations = {}
        self.colleges = {}
        self.mentors = {}
        self.agreements = {}
        self.cohorts = {}
        self.offers = {}
        self.scholars = {}
        self.training_records = {}
        self.meetings = {}
        self.internships = {}


store = Store()


def now():
    """Current logical-clock instant (aware UTC datetime)."""
    return store.clock


def new_id():
    """Server-minted UUID, no type prefix (PRD 2.5)."""
    return str(uuid.uuid4())


def add(collection, fields, common=True):
    """Insert a new entity dict. common=True adds updated_at/version (PRD 2.5);
    Evaluation passes common=False (immutable: only id + created_at)."""
    store.seq += 1
    e = dict(fields)
    e["id"] = new_id()
    e["_seq"] = store.seq
    e["created_at"] = now()
    if common:
        e["updated_at"] = now()
        e["version"] = 1
    collection[e["id"]] = e
    return e


def touch(e):
    """Refresh updated_at and bump version on a mutation (PRD 2.5)."""
    e["updated_at"] = now()
    e["version"] += 1
