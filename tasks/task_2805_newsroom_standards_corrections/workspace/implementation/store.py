"""In-memory data store and the logical newsroom clock.

Storage is process-local Python dicts keyed by id.  The store starts EMPTY on
every boot: no entity is ever seeded, preloaded or hardcoded here.
"""

import itertools
import uuid
from datetime import datetime, timezone, timedelta
from decimal import Decimal

# PRD 2.5: before any caller sets it, the logical clock reads exactly
# 2026-08-01T00:00:00Z, and it never falls back to the host's actual time.
LOGICAL_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.newsrooms = {}
        self.journalists = {}
        self.reviewers = {}
        self.stories = {}
        self.source_approvals = {}
        self.reviews = {}
        self.assignments = {}
        self.corrections = {}
        self.investigations = {}
        self.disclosures = {}
        self.activities = {}
        self.training_records = {}
        self.audit_events = {}
        self.clock = LOGICAL_EPOCH
        self._counter = itertools.count(1)

    def next_seq(self):
        return next(self._counter)


db = Store()


def now():
    """Current reading of the logical clock."""
    return db.clock


def set_clock(dt):
    db.clock = dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_iso(value):
    """Parse an ISO 8601 instant; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def base_record(with_version=True):
    """Common fields (PRD 2.4). created_at/updated_at come from the logical clock."""
    ts = now()
    rec = {
        "id": new_id(),
        "created_at": ts,
        "_seq": db.next_seq(),
    }
    if with_version:
        rec["updated_at"] = ts
        rec["version"] = 1
    return rec


def touch(rec):
    """A mutation: refresh updated_at and advance version by exactly 1."""
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 0) + 1


def ordered(records):
    """Default list ordering: creation timestamp ascending, insertion as tie-break."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def ordered_by(records, field):
    return sorted(records, key=lambda r: (r[field], r["_seq"]))


DEC0 = Decimal("0.00")
