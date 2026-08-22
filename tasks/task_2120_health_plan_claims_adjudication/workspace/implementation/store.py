"""In-memory store, id/timestamp minting and the server's logical clock.

Storage is process-local Python dictionaries keyed by id. Nothing is persisted
and nothing is seeded: every row is created by an API call.
"""

import itertools
import uuid
from datetime import datetime, timezone, date

from flask import g

# Before the clock has ever been set it reads exactly 2026-08-01T00:00:00Z
# (PRD 2.4). The engine never falls back to real wall-clock time for business
# comparisons.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "benefit_plans",
    "fee_schedule_rates",
    "members",
    "member_coverages",
    "benefit_accumulators",
    "providers",
    "provider_contracts",
    "edit_rules",
    "authorizations",
    "claims",
    "claim_lines",
    "remittance_advices",
    "adjudication_events",
)


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self._seq = itertools.count(1)
        self.clock = DEFAULT_CLOCK

    # -- identity / time ----------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        return next(self._seq)

    def now_iso(self):
        """Real wall-clock insertion timestamp for created_at / updated_at."""
        return format_ts(datetime.now(timezone.utc))

    # -- logical clock ------------------------------------------------------
    def clock_iso(self):
        return format_ts(self.clock)

    def clock_date(self):
        return self.clock.date().isoformat()

    def set_clock(self, moment):
        self.clock = moment

    # -- row lifecycle ------------------------------------------------------
    def insert(self, collection, row):
        row["id"] = self.new_id()
        stamp = self.now_iso()
        row["created_at"] = stamp
        if row.get("_common", True):
            row["updated_at"] = stamp
            row["version"] = 1
        row["_seq"] = self.next_seq()
        getattr(self, collection)[row["id"]] = row
        created = getattr(g, "_created_rows", None)
        if created is None:
            created = set()
            g._created_rows = created
        created.add(id(row))
        return row

    def touch(self, row):
        """Mark a row as mutated by the current request.

        A mutation a row suffers as a side effect is a mutation like any other:
        it refreshes updated_at and increases version (PRD 2.9). A row moves by
        exactly one version per API operation no matter how many times the
        operation writes it, and a row created by this request stays at 1.
        """
        if not row.get("_common", True):
            return row
        touched = getattr(g, "_touched_rows", None)
        if touched is None:
            touched = set()
            g._touched_rows = touched
        key = id(row)
        if key in touched:
            return row
        touched.add(key)
        if key in getattr(g, "_created_rows", set()):
            return row
        row["updated_at"] = self.now_iso()
        row["version"] = row.get("version", 1) + 1
        return row

    # -- helpers ------------------------------------------------------------
    def values(self, collection):
        return list(getattr(self, collection).values())


def format_ts(moment):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    moment = moment.astimezone(timezone.utc)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (moment.microsecond // 1000)


def parse_iso_instant(value):
    """Parse an ISO 8601 instant, returning an aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        moment = datetime.fromisoformat(text)
    except ValueError:
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(timezone.utc)


def parse_date(value):
    """Parse a strict ISO YYYY-MM-DD calendar date, or None."""
    if not isinstance(value, str) or len(value) != 10 or value[4] != "-" or value[7] != "-":
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def sort_key_created(row):
    """created_at ascending, with the insertion sequence as a stable resolver.

    No ordering in this engine ever falls back to a surrogate identifier
    (PRD 2.5); the sequence only makes the created_at ordering total when two
    rows land inside the same millisecond.
    """
    return (row["created_at"], row["_seq"])


db = Store()
