"""In-memory store, logical clock, and timestamp helpers.

Storage is dicts keyed by id; every byte of state vanishes on process exit.
Nothing is seeded at startup: every dict starts empty.
"""
import uuid
from datetime import datetime, timezone

import constants as C


def parse_iso(value):
    """Parse an ISO 8601 string into an aware UTC datetime. Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts3(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD section 2.5)."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_dt(dt):
    """Canonical UTC rendering for clock/input datetimes: seconds precision,
    milliseconds only when the value carries sub-second precision."""
    if dt is None:
        return None
    if dt.microsecond:
        return fmt_ts3(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


class Store:
    def __init__(self):
        self.clock = parse_iso(C.CLOCK_START_ISO)
        self.seq = 0
        self.cycles = {}
        self.candidates = {}
        self.centers = {}
        self.bookings = {}
        self.submissions = {}
        self.artifacts = {}
        self.assessors = {}
        self.benchmarks = {}
        self.assignments = {}
        self.certifications = {}
        self.renewals = {}
        self.programs = {}
        self.stipends = {}


DB = Store()


def now():
    return DB.clock


def new_id():
    return str(uuid.uuid4())


def next_seq():
    DB.seq += 1
    return DB.seq


def stamp_new(entity):
    """Common fields (PRD section 2.5) applied at creation."""
    entity["created_at"] = now()
    entity["updated_at"] = now()
    entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    """updated_at refreshes and version increments on every mutation."""
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 1) + 1
    return entity
