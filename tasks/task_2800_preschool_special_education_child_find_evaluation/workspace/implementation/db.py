"""In-memory data store and the logical clock (PRD section 2.4).

The store starts completely empty on every boot: no entity is ever seeded.
"""
import itertools
import uuid
from datetime import datetime, timezone

# Logical clock default until a DistrictAdmin moves it.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "children",
    "community_sites",
    "providers",
    "screening_events",
    "screening_slots",
    "referrals",
    "consent_records",
    "evaluation_cases",
    "domain_assessments",
    "service_plans",
    "service_lines",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self.clock_echo = None
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def now_utc():
    """Logical clock reading (never the wall clock for business rules)."""
    return db.clock


def clock_date():
    return db.clock.date()


def new_id():
    return str(uuid.uuid4())


def fmt_dt(value):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    value = value.astimezone(timezone.utc)
    return value.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (value.microsecond // 1000)


def fmt_date(value):
    return None if value is None else value.isoformat()


def _wall():
    return datetime.now(timezone.utc)


def base_row():
    stamp = _wall()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(row):
    """Refresh updated_at and increment version (PRD section 2.4 cascade rule)."""
    row["updated_at"] = _wall()
    row["version"] += 1
    return row


def ordered(rows):
    """Deterministic list ordering: created_at ascending."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def common_fields(row):
    return {
        "id": row["id"],
        "created_at": fmt_dt(row["created_at"]),
        "updated_at": fmt_dt(row["updated_at"]),
        "version": row["version"],
    }
