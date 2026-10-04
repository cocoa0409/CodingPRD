import re
import uuid
import threading
from datetime import datetime, timezone, date

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class Store:
    """In-memory store. Starts empty on every boot; no seeding."""

    def __init__(self):
        self.sites = {}
        self.schools = {}
        self.applications = {}
        self.members = {}
        self.teams = {}
        self.assignments = {}
        self.students = {}
        self.hour_entries = {}
        self.payments = {}
        self.reports = {}
        # Logical clock: before any set call it reads exactly 2026-09-01T00:00:00Z
        self.clock_iso = "2026-09-01T00:00:00Z"
        self.clock_dt = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0
        self.lock = threading.RLock()


store = Store()


def new_id():
    return str(uuid.uuid4())


def next_seq():
    store.seq += 1
    return store.seq


def now_iso():
    """Wall-clock timestamp for created_at/updated_at: ISO8601 UTC, 3 fractional digits."""
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def clock_date():
    return store.clock_dt.date()


def clock_date_str():
    return store.clock_dt.date().isoformat()


def set_clock(iso_str):
    dt = parse_iso8601(iso_str)
    store.clock_dt = dt
    store.clock_iso = iso_str


def parse_iso8601(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    t = s.strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    dt = datetime.fromisoformat(t)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    """Strict YYYY-MM-DD parse; returns datetime.date. Raises ValueError."""
    if not isinstance(s, str) or not DATE_RE.match(s):
        raise ValueError("malformed date")
    return date.fromisoformat(s)


def new_entity(extra=None):
    """Base record with common fields. ServiceHourEntry uses new_entry() instead."""
    e = {
        "id": new_id(),
        "created_at": now_iso(),
        "updated_at": None,  # set below to same value as created_at
        "version": 1,
        "_seq": next_seq(),
    }
    e["updated_at"] = e["created_at"]
    if extra:
        e.update(extra)
    return e


def touch(e):
    """Every mutation (incl. cascaded) refreshes updated_at and bumps version."""
    e["updated_at"] = now_iso()
    e["version"] += 1
