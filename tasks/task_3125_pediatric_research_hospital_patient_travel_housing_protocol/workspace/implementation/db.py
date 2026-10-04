"""In-memory data store. No seeding, no persistence, no disk state at all.

Every map starts empty on each process boot; the per-test-server isolation harness
re-runs start.sh before every test, which therefore guarantees a fresh boot.
"""

import uuid
from datetime import datetime, timedelta, timezone

DEFAULT_CLOCK = "2026-09-01T00:00:00Z"


def _empty_state():
    return {
        "funds": {},
        "protocols": {},
        "referrals": {},
        "enrollments": {},
        "pledges": {},
        "housing_assignments": {},
        "housing_facilities": {},
        "travel_arrangements": {},
        "clinics": {},
        "affiliations": {},
        "milestones": {},
        "studies": {},
        "survivorship_enrollments": {},
        "follow_ups": {},
        "services": {},
        "ledgers": {},
        "sibling_services": {},
        "holds": {},
        "clock": DEFAULT_CLOCK,
    }


DB = _empty_state()


def new_id():
    return str(uuid.uuid4())


# --- logical clock -----------------------------------------------------------

def clock_text():
    return DB["clock"]


def clock():
    """The logical clock as a timezone-aware datetime."""
    return parse_iso(DB["clock"])


def set_clock(value):
    DB["clock"] = normalize_iso(value)


# --- timestamps --------------------------------------------------------------

def now_iso():
    """Logical-clock instant, ISO 8601 UTC with three fractional digits."""
    return clock().strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (clock().microsecond // 1000)


def parse_iso(value):
    """Parse an ISO 8601 instant; returns a UTC-aware datetime.

    Accepts 'Z', '+00:00', a trailing fractional part of any length, and a bare
    'YYYY-MM-DDTHH:MM:SS'.
    """
    if value is None:
        raise ValueError("missing timestamp")
    if isinstance(value, datetime):
        dt = value
    else:
        if not isinstance(value, str):
            raise ValueError("timestamp must be a string")
        text = value.strip()
        if not text:
            raise ValueError("empty timestamp")
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                raise ValueError("unparseable timestamp: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def normalize_iso(value):
    dt = parse_iso(value)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def add_months(dt, months):
    """Calendar-correct month addition, clamping the day to the target month."""
    month_index = dt.month - 1 + months
    year = dt.year + month_index // 12
    month = month_index % 12 + 1
    day = dt.day
    while day > 28:
        try:
            return dt.replace(year=year, month=month, day=day)
        except ValueError:
            day -= 1
    return dt.replace(year=year, month=month, day=day)


def add_years(dt, years):
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:  # 29 Feb on a non-leap target year
        return dt.replace(year=dt.year + years, day=28)


def whole_days_between(start, end):
    """Whole days between two instants (floor of the elapsed delta)."""
    return int((end - start).total_seconds() // 86400)


def age_in_whole_years(dob, at):
    years = at.year - dob.year
    if (at.month, at.day) < (dob.month, dob.day):
        years -= 1
    return years


# --- common resource properties ---------------------------------------------

def new_row(fields):
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = now_iso()
    row["updated_at"] = row["created_at"]
    # PRD §2.10: `version` "starts at one and increments by exactly one on every
    # mutation". A freshly created row is therefore at 1; a later mutation makes 2.
    row["version"] = 1
    return row


def touch(row):
    """Every mutation refreshes updated_at and advances version by exactly one."""
    row["updated_at"] = now_iso()
    row["version"] = int(row.get("version", 0)) + 1
    return row


def touch_only(row):
    """For derived-field refreshes that are not user-visible mutations."""
    row["updated_at"] = now_iso()
    return row