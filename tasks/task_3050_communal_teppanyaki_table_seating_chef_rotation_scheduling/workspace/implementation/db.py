"""In-memory store. Nothing is seeded at startup; the process boots empty."""
import uuid
from datetime import datetime, timedelta, timezone

# Startup default clock: exactly 2026-09-01T00:00:00Z (never real wall-clock time).
DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_state = {
    "clock": DEFAULT_CLOCK,
}

STORES = [
    "venues",
    "parties",
    "tiers",
    "tables",
    "reservations",
    "seatings",
    "chefs",
    "shows",
    "maintenance_windows",
    "sushi_tickets",
    "ledger_entries",
    "protein_tickets",
]

DB = {name: {} for name in STORES}


def reset():
    """Wipe every byte of state. Only the test harness-afforded boot path uses this."""
    for name in STORES:
        DB[name] = {}
    _state["clock"] = DEFAULT_CLOCK


def now():
    return _state["clock"]


def set_clock(dt):
    _state["clock"] = dt


def new_id():
    return str(uuid.uuid4())


def fmt(dt):
    """ISO 8601 UTC; a whole-second instant is rendered without fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    head = dt.strftime("%Y-%m-%dT%H:%M:%S")
    if dt.microsecond:
        return head + "." + "%03d" % (dt.microsecond // 1000) + "Z"
    return head + "Z"


def parse_dt(value):
    """Parse an ISO 8601 instant supplied by a caller."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_row(**fields):
    """Stamp the common field set (scaffold §2.4)."""
    ts = now()
    row = dict(fields)
    row.setdefault("id", new_id())
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    return row


def touch(row, **changes):
    """Apply a mutation: bump version, refresh updated_at."""
    row.update(changes)
    row["updated_at"] = now()
    row["version"] = row.get("version", 1) + 1
    return row


def public(row):
    """Serialise a row for the wire: datetimes become ISO strings."""
    if row is None:
        return None
    out = {}
    for key, value in row.items():
        if isinstance(value, datetime):
            out[key] = fmt(value)
        else:
            out[key] = value
    return out


def public_list(rows):
    return [public(r) for r in rows]


def add(store, row):
    DB[store][row["id"]] = row
    return row


def get(store, row_id):
    return DB[store].get(row_id)


def all_of(store):
    return list(DB[store].values())


def find(store, **criteria):
    out = []
    for row in DB[store].values():
        if all(row.get(k) == v for k, v in criteria.items()):
            out.append(row)
    return out


def find_one(store, **criteria):
    for row in DB[store].values():
        if all(row.get(k) == v for k, v in criteria.items()):
            return row
    return None


def sorted_by_created(rows):
    return sorted(rows, key=lambda r: (r.get("created_at"), r.get("id")))


def add_minutes(dt, minutes):
    return dt + timedelta(minutes=minutes)


def add_days(dt, days):
    return dt + timedelta(days=days)


def minutes_between(start, end):
    """Whole minutes between two instants (floor of the delta)."""
    if start is None or end is None:
        return 0
    return int((end - start).total_seconds() // 60)