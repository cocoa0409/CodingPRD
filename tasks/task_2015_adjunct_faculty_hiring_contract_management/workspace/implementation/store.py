"""In-memory data store and the controllable logical clock.

The store starts completely empty on every boot; nothing is seeded. The
logical clock defaults to exactly 2026-08-01T00:00:00Z at startup and never
falls back to wall-clock time (PRD 2.4).
"""

from datetime import datetime, timezone


class Store:
    """A plain bag of dicts keyed by entity id."""

    def __init__(self):
        self.departments = {}
        self.terms = {}
        self.rate_schedules = {}
        self.postings = {}
        self.applications = {}
        self.credentials = {}
        self.faculty = {}
        self.sections = {}
        self.contracts = {}
        self.payroll_periods = {}
        self.payroll_entries = {}
        self.evaluations = {}
        self.retention_entries = {}

    def __getitem__(self, table):
        return getattr(self, table)


STORE = Store()

# Logical clock: a one-element mutable cell holding an aware UTC datetime.
CLOCK = [datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)]


def now_dt():
    """Return the current logical datetime (aware, UTC)."""
    return CLOCK[0]


def set_now(dt):
    CLOCK[0] = dt


def now_iso():
    """Current logical timestamp serialized as ISO 8601 UTC, 3 fractional digits."""
    return iso_ts(CLOCK[0])


def iso_ts(dt):
    """Serialize an aware UTC datetime as ISO 8601 with exactly 3 fractional
    digits and a trailing Z, e.g. 2026-08-01T00:00:00.000Z."""
    dt = dt.astimezone(timezone.utc)
    ms = dt.microsecond // 1000
    return dt.strftime("%Y-%m-%dT%H:%M:%S") + (".%03dZ" % ms)
