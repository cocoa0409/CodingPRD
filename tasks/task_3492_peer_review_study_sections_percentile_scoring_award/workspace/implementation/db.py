"""In-memory store + logical clock. Fresh, empty state on every process boot.

NO seeding: every entity is created through the declared API surface only.
"""
import itertools
import uuid
from datetime import datetime, timezone

from constants import CLOCK_START_ISO

# collection name -> {id: entity-dict}
STORE = {
    "funding_opportunities": {},
    "institutes": {},
    "institutions": {},
    "applicants": {},
    "applications": {},
    "study_sections": {},
    "reviewers": {},
    "assignments": {},
    "council_reviews": {},
    "jit_requests": {},
    "awards": {},
    "progress_reports": {},
    "award_modifications": {},
    "transfer_requests": {},
}

_seq = itertools.count(1)


def next_seq():
    """Monotonic creation sequence; stable tiebreak where created_at ties."""
    return next(_seq)


def _parse_clock_start():
    return datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


_clock = {"current": _parse_clock_start()}


def clock_now():
    return _clock["current"]


def set_clock(dt):
    _clock["current"] = dt
    return _clock["current"]


def new_id():
    # Dashed canonical UUID form ONLY (uuid4().hex is forbidden).
    return str(uuid.uuid4())


def new_entity():
    """Common system fields for a freshly created resource (PRD §2.5)."""
    now = clock_now()
    return {
        "id": new_id(),
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": next_seq(),
    }


def touch(entity):
    """Refresh updated_at and bump version on mutation (PRD §2.5)."""
    entity["updated_at"] = clock_now()
    entity["version"] = int(entity.get("version", 1)) + 1
