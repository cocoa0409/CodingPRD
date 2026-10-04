"""In-memory data store and server logical clock. No seeding — starts empty."""
import uuid
from datetime import datetime, timezone, timedelta

BOOT_UTC = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store:
    def __init__(self):
        self.circles = {}           # id -> dict
        self.members = {}           # id -> dict
        self.places = {}            # id -> dict
        self.fixes = {}             # id -> dict
        self.place_alerts = {}      # id -> dict
        self.trips = {}             # id -> dict
        self.crashes = {}           # id -> dict
        self.wellness_checks = {}   # id -> dict
        self.dispatches = {}        # id -> dict
        self.subscription_events = {}  # id -> dict
        self.consent_records = {}   # id -> dict
        self.compliance_holds = {}  # id -> dict
        self.clock = BOOT_UTC


db = Store()


def new_id():
    return uuid.uuid4().hex


def now():
    return db.clock


def iso(dt):
    """ISO 8601 UTC with three fractional digits, trailing Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + \
        f"{dt.microsecond // 1000:03d}Z"


def parse_dt(value):
    """Parse an ISO-8601 datetime string; returns aware datetime or None."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        # Date-only strings are allowed for birthdate
        try:
            dt = datetime.strptime(value.strip()[:10], "%Y-%m-%d")
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def touch(entity):
    entity["updated_at"] = now()
    entity["version"] = entity.get("version", 0) + 1


def new_entity(**fields):
    ent = {
        "id": new_id(),
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
    }
    ent.update(fields)
    return ent
