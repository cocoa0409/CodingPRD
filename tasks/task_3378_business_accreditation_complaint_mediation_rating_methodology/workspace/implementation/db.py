"""In-memory data store and the logical clock (PRD section 2.4).

Storage is plain dicts keyed by id. The store starts completely empty on every
boot; no seeding of any kind. `start.sh` re-invocation wipes all state because
each launch is a fresh process.
"""
import uuid
from datetime import datetime, timedelta, timezone

from constants import CLOCK_START_ISO

ENTITY_KINDS = (
    "bureaus",
    "consumers",
    "businesses",
    "applications",
    "invoices",
    "complaints",
    "mediation_cases",
    "arbitration_cases",
    "rating_snapshots",
    "rating_disputes",
    "advertising_reviews",
    "scam_reports",
)


class Store:
    def __init__(self):
        for kind in ENTITY_KINDS:
            setattr(self, kind, {})
        # Internal-only bookkeeping (never serialized):
        # business id -> list of suspension instants (for the 730-day window)
        self.suspension_events = {}
        # global monotone sequence for deterministic tie-breaking
        self.seq = 0
        # the logical clock; startup default pinned by PRD 2.4
        self.clock = parse_iso(CLOCK_START_ISO)

    def next_seq(self):
        self.seq += 1
        return self.seq


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------
def now():
    """Current logical-clock instant (aware UTC)."""
    return STORE.clock


def set_clock(dt):
    STORE.clock = dt


# ---------------------------------------------------------------------------
# ISO 8601 helpers
# ---------------------------------------------------------------------------
def parse_iso(value):
    """Parse an ISO 8601 string into an aware UTC datetime.

    Accepts a trailing 'Z', explicit offsets, fractional seconds, and
    date-only forms. Raises ValueError/TypeError on garbage.
    """
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    else:
        raise ValueError("not an ISO 8601 value: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso(dt):
    """Render an aware UTC datetime as ISO 8601 with three fractional digits
    and a trailing Z — the format PRD 2.5 pins on system timestamps."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_clock_value(dt):
    """Render the logical clock for the clock endpoint: second precision when
    the value lands on a whole second, else millisecond precision."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond == 0:
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    return iso(dt)


# ---------------------------------------------------------------------------
# Entity factory and mutation helpers
# ---------------------------------------------------------------------------
def new_entity(kind, fields):
    """Mint an entity of `kind` with the common system properties (PRD 2.5)."""
    ts = now()
    entity = {
        "id": str(uuid.uuid4()),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
    }
    entity.update(fields)
    entity["_seq"] = STORE.next_seq()
    getattr(STORE, kind)[entity["id"]] = entity
    return entity


def touch(entity):
    """Refresh updated_at and bump version on a mutation (PRD 2.5)."""
    entity["updated_at"] = now()
    entity["version"] += 1


def days(n):
    return timedelta(days=n)


def seconds(n):
    return timedelta(seconds=n)


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------
def serialize(entity):
    """Return a JSON-ready copy of an entity: internal keys stripped, datetime
    values rendered as ISO strings recursively."""
    out = {}
    for key, value in entity.items():
        if key.startswith("_"):
            continue
        out[key] = _serialize_value(value)
    return out


def _serialize_value(value):
    if isinstance(value, datetime):
        return iso(value)
    if isinstance(value, list):
        return [_serialize_value(v) for v in value]
    if isinstance(value, dict):
        return {k: _serialize_value(v) for k, v in value.items() if not k.startswith("_")}
    return value


# Instantiated last so every helper the constructor uses is already defined.
STORE = Store()
