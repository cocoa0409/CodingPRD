"""In-memory data store plus the server-held logical clock (PRD section 2.5).

The store starts completely empty on every boot; every entity is created via
API calls. No seeding, no file persistence.
"""
import uuid
from datetime import datetime, timezone

from constants import CLOCK_START

STORE = {
    "members": {},
    "eligibility_cases": {},
    "external_service_records": {},
    "program_tracks": {},
    "enrollments": {},
    "assessments": {},
    "claims": {},
    "appeals": {},
    "referrals": {},
    "partner_sites": {},
    "employer_partners": {},
    "placements": {},
    "community_events": {},
    "event_registrations": {},
    "surveys": {},
    "donor_reports": {},
}

# The logical clock: exactly 2026-09-01T00:00:00Z at startup, never wall clock.
_CLOCK = {"now": datetime(CLOCK_START[0], CLOCK_START[1], CLOCK_START[2],
                          CLOCK_START[3], CLOCK_START[4], CLOCK_START[5],
                          tzinfo=timezone.utc)}

# Globally monotonic insertion sequence (stable tie-break for created_at sorts)
# and the globally monotonic referral request_seq (from 1).
_SEQ = {"value": 0}
_REFERRAL_SEQ = {"value": 0}


def now():
    return _CLOCK["now"]


def set_clock(dt):
    _CLOCK["now"] = dt


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _SEQ["value"] += 1
    return _SEQ["value"]


def next_referral_seq():
    _REFERRAL_SEQ["value"] += 1
    return _REFERRAL_SEQ["value"]


def iso(dt):
    """Serialize a datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 datetime; floor to second precision (PRD: all
    datetime comparisons are evaluated at second precision). None on failure."""
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
    dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=0)
