"""In-memory data store.

Storage is a set of plain Python dicts keyed by id.  Nothing is persisted to
disk and nothing is seeded at import time: the store starts empty on every boot
so that a fresh `start.sh` invocation wipes every byte of state.
"""

import uuid
from datetime import datetime, timedelta, timezone

# The logical clock's fixed startup value (PRD section 2.9).  The server must
# never fall back to real wall-clock time before this endpoint is called.
DEFAULT_CLOCK = "2026-09-01T00:00:00.000Z"

STORE = {
    "channels": {},
    "content_items": {},
    "ad_reviews": {},
    "reference_files": {},
    "claims": {},
    "claim_disputes": {},
    "claim_appeals": {},
    "copyright_strikes": {},
    "revenue_routings": {},
    "revenue_events": {},
    "payout_batches": {},
    "channel_strikes": {},
    "membership_schedules": {},
    "channel_memberships": {},
}


def reset_store():
    for bucket in STORE.values():
        bucket.clear()


def new_id():
    """A server-minted UUID with no type prefix and no embedded entity name."""
    return str(uuid.uuid4())


def now():
    """The current logical clock instant, truncated to the second."""
    return _CLOCK["now"]


def to_iso8601(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso8601(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def add_days(dt, days):
    return dt + timedelta(days=days)


def common_fields(extra=None, created_at=None):
    """The common field set: id / created_at / updated_at / version.

    `version` starts at 1; `created_at` is fixed at creation and `updated_at`
    starts equal to it.
    """
    stamp = to_iso8601(created_at or now())
    fields = {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    if extra:
        fields.update(extra)
    return fields


def subresource_fields(extra=None, created_at=None):
    """Fields for the sub-resources that carry neither updated_at nor version."""
    fields = {
        "id": new_id(),
        "created_at": to_iso8601(created_at or now()),
    }
    if extra:
        fields.update(extra)
    return fields


def touch(record):
    """Bump a resource's version by 1 and refresh its updated_at."""
    record["version"] = record.get("version", 1) + 1
    record["updated_at"] = to_iso8601(now())
    return record


def insert(bucket, record):
    STORE[bucket][record["id"]] = record
    return record


def get(bucket, record_id):
    return STORE[bucket].get(record_id)


def all_of(bucket):
    return list(STORE[bucket].values())


def find_first(bucket, **criteria):
    for record in STORE[bucket].values():
        if all(record.get(k) == v for k, v in criteria.items()):
            return record
    return None


_CLOCK = {"now": parse_iso8601(DEFAULT_CLOCK)}


def get_clock():
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt