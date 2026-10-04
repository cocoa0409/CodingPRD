"""In-memory data store. Empty at every boot — tests build all state via the API."""
import uuid
from datetime import datetime, timezone, timedelta

STORE = {
    "programs": {},
    "patients": {},
    "providers": {},
    "cohorts": {},
    "orders": {},
    "outreach_events": {},
    "reminders": {},
    "kits": {},
    "specimens": {},
    "results": {},
    "reports": {},
}

KIT_ABANDON_DAYS = 45
RECOLLECTION_ABANDON_DAYS = 30
MAX_RECOLLECTIONS = 2
STABILIZATION_HOURS = 72
NAVIGATION_WINDOW_DAYS = 90
ADHERENCE_WINDOW_DAYS = 365
MIN_AGE = 45
MAX_AGE = 75
REMINDER_OFFSETS = {1: 7, 2: 14, 3: 28}

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
_current_clock = CLOCK_START


def now():
    return _current_clock


def set_clock(dt):
    global _current_clock
    _current_clock = dt


def new_id():
    return str(uuid.uuid4())


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    s = dt.strftime("%Y-%m-%dT%H:%M:%S")
    ms = dt.microsecond // 1000
    return f"{s}.{ms:03d}Z"


def iso_date(d):
    return d.strftime("%Y-%m-%d")


def parse_iso(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    txt = s.strip()
    if txt.endswith("Z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(s):
    if not isinstance(s, str):
        raise ValueError("not a string")
    return datetime.strptime(s.strip(), "%Y-%m-%d").date()


def date_of(dt):
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).date()


def add_days(d, n):
    return d + timedelta(days=n)


def add_hours(dt, n):
    return dt + timedelta(hours=n)


def touch(entity):
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 0) + 1


def new_entity():
    t = now()
    return {"id": new_id(), "created_at": t, "updated_at": t, "version": 1}
