"""In-memory store, logical clock and numeric helpers.

The store is empty on every boot: nothing is seeded, preloaded or hardcoded.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------- collections
terms = {}
degree_programs = {}
courses = {}
rules = {}
students = {}
enrollments = {}
certifications = {}
tutors = {}
assignments = {}
sessions = {}
events = {}
requests = {}
appeals = {}
incidents = {}

ALL_COLLECTIONS = (
    terms, degree_programs, courses, rules, students, enrollments,
    certifications, tutors, assignments, sessions, events, requests,
    appeals, incidents,
)

# PRD 2.4: before the clock has been set it reads exactly this instant, and it
# never falls back to real time.
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)
_clock = {"now": CLOCK_DEFAULT}
_seq = {"n": 0}


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def new_id():
    return str(uuid.uuid4())


def clock_now():
    return _clock["now"]


def set_clock(dt):
    _clock["now"] = dt


# ------------------------------------------------------------------ instants
def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def parse_instant(value):
    """Parse an ISO 8601 instant. Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_iso():
    return fmt_instant(clock_now())


def plus_hours(dt, hours):
    return dt + timedelta(hours=hours)


# ------------------------------------------------------------------- numbers
ZERO = Decimal("0")


def D(value):
    """Coerce a JSON scalar to Decimal without ever passing through float."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        raise ValueError("bool is not numeric")
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def q(value, places):
    exp = Decimal(1).scaleb(-places)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def q0(value):
    return int(D(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def q1(value):
    return q(value, 1)


def q2(value):
    return q(value, 2)


def q4(value):
    return q(value, 4)


# ------------------------------------------------------- common field helpers
def stamp_new(row):
    """Attach id/created_at/updated_at/version (PRD 2.4)."""
    row["id"] = new_id()
    row["created_at"] = now_iso()
    row["updated_at"] = row["created_at"]
    row["version"] = 1
    row["_seq"] = next_seq()
    return row


def stamp_session(row):
    """SupportSession carries only id and created_at (PRD 2.4)."""
    row["id"] = new_id()
    row["created_at"] = now_iso()
    row["_seq"] = next_seq()
    return row


def touch(row):
    """Advance updated_at and version on a mutated row (PRD 2.11)."""
    row["updated_at"] = now_iso()
    row["version"] = int(row.get("version", 0)) + 1
    return row


def by_created(rows):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
