"""In-memory data store and logical clock. Store starts empty on every boot."""
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK_STR = "2026-09-01T00:00:00Z"


def parse_dt(value):
    """Parse an ISO-8601 string into an aware UTC datetime. Raises ValueError."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        s = value.strip()
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
    else:
        raise ValueError("not a datetime")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """Format an aware datetime as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def new_id():
    return str(uuid.uuid4())


class Store:
    def __init__(self):
        self.jurisdictions = {}
        self.sites = {}
        self.deployments = {}
        self.plans = {}
        self.revisions = {}
        self.permits = {}
        self.printer_setups = {}
        self.batches = {}
        self.weather = {}
        self.print_jobs = {}
        self.interruptions = {}
        self.inspections = {}
        self.trade_tasks = {}
        self.idempotency = {}


store = Store()

_clock = {"now": parse_dt(DEFAULT_CLOCK_STR)}


def now():
    return _clock["now"]


def set_clock(value):
    _clock["now"] = parse_dt(value)
    return _clock["now"]


def stamp_created(entity):
    ts = fmt_dt(now())
    entity["id"] = new_id()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    return entity


def touch(entity):
    entity["updated_at"] = fmt_dt(now())
    entity["version"] = entity.get("version", 1) + 1
    return entity
