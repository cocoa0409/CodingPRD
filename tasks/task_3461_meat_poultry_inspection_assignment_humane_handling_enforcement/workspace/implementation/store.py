"""In-memory data store, logical clock, id/timestamp helpers.

Every start.sh invocation boots a completely fresh, EMPTY system: no seeding,
no file persistence. All temporal rules evaluate against the logical clock,
which defaults to exactly 2026-09-01T00:00:00Z with no wall-clock fallback.
"""
import uuid
from datetime import datetime, timezone


# ---------------------------------------------------------------------------
# Logical clock (PRD §2.4)
# ---------------------------------------------------------------------------
_DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
_clock_dt = None          # datetime (tz-aware UTC)
_clock_echo = None        # last client-supplied string, echoed on set responses


def _parse_iso(value):
    """Parse an ISO 8601 timestamp into a tz-aware UTC datetime.

    Raises ValueError on unparseable input. Naive input is treated as UTC.
    """
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def clock_reset():
    global _clock_dt, _clock_echo
    _clock_dt = _parse_iso(_DEFAULT_CLOCK_ISO)
    _clock_echo = _DEFAULT_CLOCK_ISO


def clock_now():
    return _clock_dt


def clock_set(value):
    """Set the logical clock from a client string. Returns the echo string."""
    global _clock_dt, _clock_echo
    dt = _parse_iso(value)
    _clock_dt = dt
    _clock_echo = value
    return _clock_echo


def clock_echo():
    return _clock_echo


# ---------------------------------------------------------------------------
# Timestamp / id helpers
# ---------------------------------------------------------------------------

def iso3(dt):
    """ISO 8601 UTC string with exactly three fractional digits (PRD §2.6)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def wallclock_iso3():
    """Server wall-clock timestamp for meta.api_request_timestamp (PRD §2.2)."""
    return iso3(datetime.now(timezone.utc))


def new_id():
    """Server-minted UUID with no type prefix (PRD §2.6)."""
    return str(uuid.uuid4())


# ---------------------------------------------------------------------------
# Data store
# ---------------------------------------------------------------------------
db = None
_seq_counter = None


def reset_store():
    """(Re)create the empty store. Called once at module import (fresh boot)."""
    global db, _seq_counter
    db = {
        "establishments": {},
        "grant_applications": {},
        "inspectors": {},
        "shift_windows": {},
        "shift_assignments": {},
        "noncompliance_records": {},
        "enforcement_actions": {},
        "humane_events": {},
        "pathogen_samples": {},
        "label_applications": {},
        "recalls": {},
        "effectiveness_checks": {},
        "appeals": {},
    }
    _seq_counter = [0]
    clock_reset()


def next_seq():
    _seq_counter[0] += 1
    return _seq_counter[0]


def stamp_new(entity, with_version=True):
    """Populate common system fields on a freshly created entity (PRD §2.6)."""
    now = clock_now()
    entity["id"] = new_id()
    entity["created_at"] = now
    if with_version:
        entity["updated_at"] = now
        entity["version"] = 1
    entity["_seq"] = next_seq()
    return entity


def touch(entity):
    """Register a mutation: refresh updated_at and bump version (PRD §2.6)."""
    entity["updated_at"] = clock_now()
    entity["version"] = int(entity.get("version", 1)) + 1


def insert(kind, entity):
    db[kind][entity["id"]] = entity
    return entity


def get(kind, entity_id):
    if not isinstance(entity_id, str):
        return None
    return db[kind].get(entity_id)


def all_of(kind):
    return list(db[kind].values())


def find(kind, **conditions):
    out = []
    for row in db[kind].values():
        ok = True
        for key, val in conditions.items():
            if row.get(key) != val:
                ok = False
                break
        if ok:
            out.append(row)
    return out


def serialize(obj):
    """Deep-convert an entity dict to its JSON-safe public form.

    Internal keys (prefixed ``_``) are stripped; datetimes render with three
    fractional digits; everything else passes through.
    """
    if isinstance(obj, dict):
        out = {}
        for key, val in obj.items():
            if isinstance(key, str) and key.startswith("_"):
                continue
            out[key] = serialize(val)
        return out
    if isinstance(obj, list):
        return [serialize(v) for v in obj]
    if isinstance(obj, datetime):
        return iso3(obj)
    return obj


reset_store()
