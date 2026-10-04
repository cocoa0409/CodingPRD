"""In-memory data store and logical clock.

The store starts empty on every boot — no seeding anywhere.
The logical clock defaults to 2026-09-01T00:00:00Z and is advanced only via
POST /integrity/_clock/set_current_utc. Wall-clock time is never used for
business logic; it is used only for api_request_timestamp in the meta envelope
(which the PRD requires to be an ISO8601 UTC timestamp).
"""
from datetime import datetime, timezone, timedelta

# Entity tables: dict id -> dict
DB = {
    "institutions": {},
    "lms_integrations": {},
    "instructors": {},
    "students": {},
    "assignments": {},
    "submissions": {},
    "source_documents": {},
    "match_fragments": {},
    "similarity_reports": {},
    "ai_writing_assessments": {},
    "repository_deposits": {},
    "data_retention_policies": {},
    "grade_entries": {},
}

# Logical clock state (millisecond precision)
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = DEFAULT_CLOCK


def now_logical():
    return _clock


def set_logical(dt):
    global _clock
    _clock = dt


def parse_iso(s):
    """Parse an ISO8601 timestamp. Accepts trailing Z."""
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_iso(dt):
    """Format as ISO8601 UTC with three fractional digits and Z suffix."""
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + ".%03dZ" % ms
