"""Time, identity, and record-lifecycle helpers.

Timestamps are stored on records as timezone-aware UTC datetimes and rendered
as ISO 8601 UTC with three fractional digits (PRD section 2.5) at
serialization time (see envelope.serialize).
"""
import uuid
from datetime import datetime, timezone

from store import db


def new_id():
    """Server-minted UUID with no type prefix (PRD section 2.5).

    Rendered in the canonical RFC 4122 8-4-4-4-12 hyphenated form — the
    standard textual representation of "a UUID" for a resource identity
    field.
    """
    return str(uuid.uuid4())


def now():
    """Current logical instant (never wall clock)."""
    return db.clock


def today():
    """Current logical date (UTC date portion of the logical clock)."""
    return db.clock.date()


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits, e.g. 2025-05-24T10:30:00.123Z."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 datetime into an aware UTC datetime, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(value):
    """Parse a strict YYYY-MM-DD date, or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def next_seq():
    db.seq += 1
    return db.seq


def stamp_new(rec, versioned=True):
    """Populate system identity fields on a freshly created record.

    versioned resources carry created_at/updated_at/version; immutable records
    (AcceptanceTest, CustodyTransfer) carry only id and created_at (PRD 2.5).
    """
    ts = now()
    rec["id"] = new_id()
    rec["created_at"] = ts
    if versioned:
        rec["updated_at"] = ts
        rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """Refresh updated_at and bump version on any mutation (PRD 2.5)."""
    rec["updated_at"] = now()
    rec["version"] += 1
