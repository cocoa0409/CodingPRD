"""In-memory data store, the logical compliance clock (PRD 2.5) and row helpers.

The store starts completely empty on every boot: nothing is seeded, preloaded or
hardcoded. Every entity is created through the declared API surface.
"""

import re
import threading
import uuid
from datetime import datetime, timedelta, timezone

from envelope import wall_now_iso
from errors import ApiError

LOCK = threading.RLock()

# The logical clock begins at exactly 2026-08-01T00:00:00Z and never falls back
# to wall-clock time for any business decision.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt](\d{2}):(\d{2}):(\d{2})(\.\d+)?(?:[Zz]|[+-]00:?00)$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


class Store(object):
    def __init__(self):
        self.administrators = {}
        self.plan_years = {}
        self.classifications = {}
        self.treatment_limitations = {}
        self.parity_tests = {}
        self.nqtl_items = {}
        self.analyses = {}
        self.vendor_requests = {}
        self.data_submissions = {}
        self.caps = {}
        self.regulator_requests = {}
        self.notices = {}
        self.clock = CLOCK_EPOCH
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def clock_now():
    return db.clock


def format_instant(moment):
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (
        moment.microsecond // 1000
    )


def clock_now_iso():
    return format_instant(db.clock)


def parse_instant(text):
    """Parse an ISO-8601 UTC instant, or return None when malformed."""
    if not isinstance(text, str):
        return None
    match = _INSTANT_RE.match(text.strip())
    if not match:
        return None
    year, month, day, hour, minute, second, frac = match.groups()
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    try:
        return datetime(
            int(year), int(month), int(day), int(hour), int(minute), int(second),
            micro, tzinfo=timezone.utc,
        )
    except ValueError:
        return None


def parse_date(text):
    """Parse a YYYY-MM-DD date, or return None when malformed."""
    if not isinstance(text, str):
        return None
    match = _DATE_RE.match(text.strip())
    if not match:
        return None
    try:
        return datetime(int(match.group(1)), int(match.group(2)), int(match.group(3)),
                        tzinfo=timezone.utc).date()
    except ValueError:
        return None


def add_days(moment, days):
    return moment + timedelta(days=int(days))


def new_row(extra=None):
    """Mint a row with the full system-managed property set (PRD 2.4)."""
    stamp = wall_now_iso()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def new_append_only_row(extra=None):
    """Participant notices carry only id and created_at (PRD 2.4)."""
    row = {
        "id": str(uuid.uuid4()),
        "created_at": wall_now_iso(),
        "_seq": db.next_seq(),
    }
    if extra:
        row.update(extra)
    return row


def touch(row):
    """A mutation refreshes updated_at and increments version by exactly 1."""
    row["updated_at"] = wall_now_iso()
    row["version"] = row["version"] + 1


def creation_key(row):
    return (row["created_at"], row["_seq"])


def sort_by_created_at(rows):
    return sorted(rows, key=creation_key)


def require(collection, row_id, error_id):
    if not isinstance(row_id, str) or row_id not in collection:
        raise ApiError(error_id)
    return collection[row_id]


def lookup_path(collection, row_id, error_id):
    row = collection.get(row_id)
    if row is None:
        raise ApiError(error_id)
    return row
