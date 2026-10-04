"""In-memory data store, logical clock, and timestamp helpers.

Storage is plain Python dicts keyed by id. The store starts empty on every
boot — no seeding, no preloading, no file persistence (per the build
contract: tests build all state via the API).

The logical clock (PRD §2.4) starts at exactly 2026-09-01T00:00:00Z and is
moved only by POST /accreditation/_clock/set_current_utc. The server never
falls back to wall-clock time for any rule; meta timestamps and all stored
stamps read this clock.
"""
import calendar
import uuid
from datetime import datetime, timedelta, timezone

from constants import CLOCK_DEFAULT_ISO


def _parse_iso_datetime(value):
    """Parse an ISO 8601 datetime string into an aware UTC datetime.

    Accepts a trailing 'Z' or an explicit offset. Returns None if unparseable.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    candidate = text
    if candidate.endswith("Z") or candidate.endswith("z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(candidate)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_iso_date(value):
    """Parse a YYYY-MM-DD calendar date; returns a date or None."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError:
        return None


def fmt_dt(dt):
    """Format an aware UTC datetime as ISO 8601 with three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "{:03d}Z".format(dt.microsecond // 1000)


def add_years(dt, years):
    """Add calendar years, clamping Feb 29 to Feb 28 on non-leap targets."""
    try:
        return dt.replace(year=dt.year + years)
    except ValueError:
        return dt.replace(year=dt.year + years, month=2, day=28)


def add_months(dt, months):
    """Add calendar months, clamping the day to the target month's length."""
    total = dt.month - 1 + months
    year = dt.year + total // 12
    month = total % 12 + 1
    day = min(dt.day, calendar.monthrange(year, month)[1])
    return dt.replace(year=year, month=month, day=day)


class Store:
    def __init__(self):
        self.institutions = {}
        self.eligibility_applications = {}
        self.review_cycles = {}
        self.assurance_arguments = {}
        self.evidence_items = {}
        self.reviewers = {}
        self.review_teams = {}
        self.team_assignments = {}
        self.decision_panels = {}
        self.action_outcomes = {}
        self.substantive_change_requests = {}
        self.indicator_reports = {}
        self.seq = 0
        self.clock = _parse_iso_datetime(CLOCK_DEFAULT_ISO)
        self.clock_verbatim = CLOCK_DEFAULT_ISO

    def next_seq(self):
        self.seq += 1
        return self.seq

    @staticmethod
    def new_id():
        return str(uuid.uuid4())

    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_dt(self.clock)

    def set_clock(self, dt, verbatim):
        self.clock = dt
        self.clock_verbatim = verbatim


# Module-level singleton. A fresh server process re-imports this module, so
# every boot starts from an empty universe with the default logical clock.
STORE = Store()
