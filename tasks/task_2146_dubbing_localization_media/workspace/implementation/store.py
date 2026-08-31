"""In-memory data store.  Nothing is seeded: every table starts empty."""
import itertools
import uuid
from datetime import datetime, timezone

TERRITORIES = ["US", "CA", "UK", "DE", "FR", "JP", "BR", "AU", "ROW"]

TABLES = [
    "titles", "cuts", "characters", "platform_specs", "voice_talents", "studios",
    "orders", "adaptations", "assignments", "sessions", "mix_jobs", "reviews",
    "retake_items", "payments",
]

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

_seq = itertools.count(1)

# datetime-valued fields, and how they are rendered
_MS_FIELDS = {"created_at", "updated_at"}
_CLOCK_FIELDS = {"start_utc", "end_utc", "delivered_at", "settled_at"}


class _Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for t in TABLES:
            setattr(self, t, {})
        self.clock = DEFAULT_CLOCK


db = _Store()


def now():
    return datetime.now(timezone.utc)


def fmt_ms(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_instant(dt):
    """Logical-clock style instant: whole seconds when there is no sub-second part."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return fmt_ms(dt)


def parse_iso(value):
    """Parse an ISO-8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str) or not value.strip():
        return None
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_row(fields):
    ts = now()
    row = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    row.update(fields)
    row["_seq"] = next(_seq)
    return row


def touch(row):
    """Register a mutation of this row: bump version by exactly 1, refresh updated_at."""
    row["version"] = row["version"] + 1
    row["updated_at"] = now()
    return row


def sort_key(row):
    return (row["created_at"], row["_seq"])


def serialize(row):
    out = {}
    for key, value in row.items():
        if key.startswith("_"):
            continue
        if isinstance(value, datetime):
            if key in _MS_FIELDS:
                out[key] = fmt_ms(value)
            else:
                out[key] = fmt_instant(value)
        else:
            out[key] = value
    return out


def serialize_all(rows):
    return [serialize(r) for r in rows]
