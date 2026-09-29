"""In-memory data store and the logical clock.

PRD 2.5: "The server runs on a logical clock rather than on wall-clock time. The
clock starts at 2026-08-01T00:00:00Z and stays there until an administrator moves
it; the server never falls back to real time for any purpose."

Nothing in this module (or anywhere else in the implementation) seeds, preloads or
hardcodes entity data: every dict below starts empty on every boot.
"""

import uuid
from datetime import datetime, timedelta, date

DEFAULT_CLOCK_UTC = "2026-08-01T00:00:00Z"

# ---------------------------------------------------------------- logical clock
_clock = datetime(2026, 8, 1, 0, 0, 0)


def now():
    """The current logical-clock instant (naive UTC datetime)."""
    return _clock


def set_clock(dt):
    global _clock
    prev = _clock
    _clock = dt
    return prev


# --------------------------------------------------------------- record tables
programs = {}
youths = {}
outreach_contacts = {}
admissions = {}
guardian_notifications = {}
safety_screenings = {}
reunification_cases = {}
mediation_sessions = {}
tlp_placements = {}
savings_entries = {}
life_skills_completions = {}
education_enrollments = {}
governance_proposals = {}
governance_votes = {}

_seq_counter = 0


def next_seq():
    global _seq_counter
    _seq_counter += 1
    return _seq_counter


def new_id():
    """PRD 2.4: 'a server-minted UUID string carrying no type prefix of any kind'."""
    return str(uuid.uuid4())


# ------------------------------------------------------------------ formatting
def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4/2.5)."""
    if dt is None:
        return None
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_instant(value):
    """Parse an ISO 8601 UTC instant. Returns a naive UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if "T" not in text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is not None:
        offset = dt.utcoffset()
        dt = dt.replace(tzinfo=None)
        if offset:
            dt = dt - offset
    return dt


def parse_date(value):
    """PRD 2.5: date_of_birth is 'a calendar date in YYYY-MM-DD form with no time
    component at all'."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


# --------------------------------------------------------- audit-field helpers
def stamp_new(rec, versioned=True):
    """Attach the common fields of PRD 2.4 to a brand-new record."""
    rec["id"] = new_id()
    rec["created_at"] = now()
    if versioned:
        rec["updated_at"] = now()
        rec["version"] = 1
    rec["_seq"] = next_seq()
    return rec


def touch(rec):
    """PRD 2.4: refresh updated_at and increment version by exactly 1.

    Called once per record per mutation, including server-initiated cascade
    mutations of derived fields.
    """
    rec["updated_at"] = now()
    rec["version"] = rec.get("version", 0) + 1
    return rec


def ordered(rows):
    """PRD 2.3 default ordering: ascending created_at.

    The logical clock does not advance on its own, so many records legitimately
    share a created_at; the internal insertion sequence keeps the order stable and
    still ascending by creation time.
    """
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def hours(n):
    return timedelta(hours=n)


def day_span(a, b):
    """Whole calendar days from the UTC calendar date of a to that of b."""
    return (b.date() - a.date()).days
