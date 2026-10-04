"""In-memory store for the rating-agency service.

Storage is a set of plain Python dicts keyed by row id.  Nothing is persisted:
no SQLite file, no JSON dump, no /tmp cache.  Because the process is the store,
re-invoking start.sh starts from a genuinely empty system.

The store is EMPTY at import time.  No entity is seeded, preloaded, registered
or hardcoded here: every row a caller observes was created through a declared
endpoint.  The only startup value is the logical clock's documented default
instant (PRD section 2.8 / SCAFFOLD endpoint table), which is clock-sourced
system state rather than entity data.
"""

import uuid
from datetime import datetime, timedelta, timezone

# Logical clock default — PRD section 2.8: "its startup default is exactly
# 2026-09-01T00:00:00Z".  This is the single temporal source; wall-clock time
# is never consulted for business dating.
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    """All collections, keyed by row id."""

    COLLECTIONS = (
        "methodologies",
        "rated_entities",
        "engagement_letters",
        "rating_requests",
        "analysts",
        "team_assignments",
        "conflict_screenings",
        "rating_committees",
        "committee_votes",
        "rating_decisions",
        "issuer_appeals",
        "surveillance_reviews",
        "rating_action_events",
        "appearance_reconciliations",
        "review_slots",
        "compensation_records",
        "look_back_reviews",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK

    def clear(self):
        for name in self.COLLECTIONS:
            getattr(self, name).clear()
        self.clock = DEFAULT_CLOCK


db = Store()


def now():
    """Current instant on the logical clock."""
    return db.clock


def new_id():
    """Server-minted UUID string with no type prefix (PRD section 2.5)."""
    return str(uuid.uuid4())


def iso(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_ts(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
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


def age_ref():
    """A value guaranteed to sort before any stored row."""
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def base_row(common=True):
    """Build the common shape: id / created_at / updated_at / version."""
    stamp = now()
    row = {"id": new_id(), "created_at": stamp}
    if common:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Bump updated_at and version on a mutation (common shape only)."""
    if "updated_at" in row:
        row["updated_at"] = now()
    if "version" in row:
        row["version"] = int(row.get("version", 1)) + 1
    return row


def bump_version(row):
    """Advance the OCC version without touching updated_at."""
    row["version"] = int(row.get("version", 1)) + 1
    return row


def days_later(instant, days):
    return instant + timedelta(days=days)


def months_later(instant, months):
    """Cycle length in months, applied as 30-day months."""
    return instant + timedelta(days=30 * int(months))