"""In-memory data store plus the logical clock.

Every byte of state lives in this process only.  Nothing is seeded: the store
starts completely empty on every boot and all entities are built through the
declared API surface.
"""
import itertools
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.5: the logical clock starts at this instant on every fresh boot and is
# never allowed to fall back to the host wall clock.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_COLLECTIONS = (
    "programs",
    "gaps",
    "suppliers",
    "plant_lines",
    "plant_audits",
    "items",
    "cost_models",
    "studies",
    "artwork_rounds",
    "label_claims",
    "specifications",
    "production_runs",
    "complaints",
    "cost_change_requests",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in _COLLECTIONS:
            setattr(self, name, {})
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """Current logical-clock instant (never the wall clock)."""
    return db.clock


def set_clock(value):
    db.clock = value


def new_id():
    return str(uuid.uuid4())


def next_seq():
    return db.next_seq()


def iso(value):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return "%s.%03dZ" % (value.strftime("%Y-%m-%dT%H:%M:%S"), value.microsecond // 1000)


def parse_dt(raw):
    """Parse an ISO 8601 UTC datetime.  Returns None when unparseable."""
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if not text:
        return None
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except (ValueError, TypeError):
        return None
    if parsed.tzinfo is None:
        return None
    offset = parsed.utcoffset()
    if offset is None or offset.total_seconds() != 0:
        return None
    return parsed.astimezone(timezone.utc)


def days_before(count):
    return now() - timedelta(days=count)


def minutes(delta):
    return delta.total_seconds() / 60.0
