"""In-memory data store and the logical UTC clock.

Nothing is seeded here: every collection starts empty on every boot and all
rows are created by the declared API endpoints.
"""
import uuid
from datetime import datetime, timedelta, timezone

# PRD 2.10: the logical clock starts at exactly this instant on every boot.
INITIAL_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "patrons",
    "partners",
    "agreements",
    "rotas",
    "rota_entries",
    "bib_items",
    "requests",
    "offers",
    "clearances",
    "shipments",
    "loans",
    "deliveries",
    "pod_orders",
    "invoices",
    "lending_charges",
    "notifications",
)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = INITIAL_CLOCK
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


def new_id():
    return str(uuid.uuid4())


def now():
    """The current logical UTC instant (never the wall clock)."""
    return db.clock


def iso_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse an ISO 8601 instant. Raises ValueError when unparseable."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("not an instant")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def add_days(dt, days):
    """Add whole days, preserving time-of-day."""
    return dt + timedelta(days=days)


def add_hours(dt, hours):
    return dt + timedelta(hours=hours)


def floor_days(later, earlier):
    """Elapsed whole days: floor of the second difference over 86400."""
    return int((later - earlier).total_seconds()) // 86400


def touch(row):
    """Record a mutation: refresh updated_at and increment version."""
    row["updated_at"] = now()
    row["version"] = row.get("version", 0) + 1
    return row


def base_row():
    return {
        "id": new_id(),
        "created_at": now(),
        "updated_at": now(),
        "version": 1,
        "_seq": db.next_seq(),
    }


def serialize(row):
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            out[key] = iso_ms(value)
        else:
            out[key] = value
    return out


def by_created(rows):
    """Default list order: created_at ascending, insertion order as tiebreak."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))
