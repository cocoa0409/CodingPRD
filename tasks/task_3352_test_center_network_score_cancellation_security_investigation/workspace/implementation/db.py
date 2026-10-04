"""In-memory data store, logical clock, and timestamp machinery.

Storage is Python dicts keyed by id only. A fresh process boots with empty
dicts; nothing is seeded. The logical clock starts at exactly
2026-09-01T00:00:00Z per PRD section 2.5 and only moves via
POST /ets/_clock/set_current_utc.
"""

import uuid
from datetime import datetime, timedelta, timezone

UTC = timezone.utc

# ---------------------------------------------------------------------------
# Entity stores (empty at boot; populated exclusively through the API surface)
# ---------------------------------------------------------------------------
test_centers = {}
staff_members = {}
audits = {}
sessions = {}
examinees = {}
registrations = {}
check_ins = {}
irregularity_reports = {}
score_records = {}
review_cases = {}
score_reports = {}
accommodation_requests = {}

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.5)
# ---------------------------------------------------------------------------
_clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=UTC)


def get_clock():
    return _clock


def set_clock(dt):
    global _clock
    _clock = dt


# ---------------------------------------------------------------------------
# Entity timestamps: derived from the logical clock but strictly increasing
# (monotonic at millisecond precision) so created_at ordering never ties,
# which the waitlist promotion rule relies on (PRD 3.3).
# ---------------------------------------------------------------------------
_last_stamp = None


def new_id():
    return str(uuid.uuid4())


def _fmt3(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    return dt.strftime('%Y-%m-%dT%H:%M:%S.') + '{:03d}Z'.format(dt.microsecond // 1000)


def fmt_ts(dt):
    if dt is None:
        return None
    return _fmt3(dt)


def fmt_clock(dt):
    """Clock/deadline rendering: no fraction when the value is whole seconds,
    matching the PRD 2.5 literal '2026-09-01T00:00:00Z'."""
    if dt is None:
        return None
    if dt.microsecond == 0:
        return dt.strftime('%Y-%m-%dT%H:%M:%SZ')
    return _fmt3(dt)


def new_stamp():
    global _last_stamp
    candidate = _clock
    if _last_stamp is not None and candidate <= _last_stamp:
        candidate = _last_stamp + timedelta(milliseconds=1)
    _last_stamp = candidate
    return candidate


def stamp_created(entity):
    ts = new_stamp()
    entity['created_at'] = ts
    entity['updated_at'] = ts
    entity['version'] = 1


def touch(entity):
    """PRD 2.4: updated_at refreshed and version incremented by exactly 1 on
    every mutation, including system cascade/recompute mutations."""
    entity['updated_at'] = new_stamp()
    entity['version'] += 1
