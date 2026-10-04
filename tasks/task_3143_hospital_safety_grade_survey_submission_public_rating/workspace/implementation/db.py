"""In-memory data store, logical clock and common-field helpers.

Everything lives in module-level dicts. A fresh process boot wipes every byte
of state; nothing is seeded, preloaded or persisted to disk.
"""

import uuid
from datetime import datetime, timezone

from decimal import Decimal, ROUND_HALF_UP

# ---------------------------------------------------------------------------
# Logical clock — startup default is exactly 2026-09-01T00:00:00Z and the
# server never falls back to wall-clock time.
# ---------------------------------------------------------------------------

CLOCK_DEFAULT = "2026-09-01T00:00:00Z"


def parse_instant(value):
    """Parse an ISO 8601 instant into an aware UTC datetime (whole seconds)."""
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
            raise ValueError("unparseable instant: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0)


def format_instant(dt):
    """Render an instant as ISO 8601 UTC with three fractional digits."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def format_wall_clock():
    """Render the current wall-clock instant with three fractional digits."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (now.microsecond // 1000)) + "Z"


class LogicalClock:
    def __init__(self):
        self.current = parse_instant(CLOCK_DEFAULT)

    def now(self):
        return self.current

    def set(self, to_iso8601):
        self.current = parse_instant(to_iso8601)
        return self.current


clock = LogicalClock()


# ---------------------------------------------------------------------------
# Numeric discipline — round half up, never banker's rounding, never floats.
# ---------------------------------------------------------------------------

def to_decimal(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, dp):
    quantum = Decimal(1).scaleb(-int(dp))
    return to_decimal(value).quantize(quantum, rounding=ROUND_HALF_UP)


def dec_to_json(value):
    """Strings for non-integral decimals; ints for integral ones."""
    if value is None:
        return None
    d = to_decimal(value)
    if d == d.to_integral_value():
        return int(d)
    text = format(d.normalize(), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return float(text)


def num(value):
    """JSON-friendly rendering for response payloads."""
    return dec_to_json(value)


# ---------------------------------------------------------------------------
# The store — every collection is a dict keyed by id.
# ---------------------------------------------------------------------------

class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.hospitals = {}
        self.methodology_versions = {}
        self.hospital_methodology_versions = {}
        self.pending_methodology_changes = {}
        self.surveys = {}
        self.survey_measures = {}
        self.reanalysis_requests = {}
        self.hospital_measure_sets = {}
        self.score_runs = {}
        self.release_cycles = {}
        self.grades = {}
        self.hospital_reviews = {}
        self.correction_requests = {}
        self.employers = {}


store = Store()


# ---------------------------------------------------------------------------
# Identity and common properties
# ---------------------------------------------------------------------------

UUID_NAMESPACE = uuid.UUID("6f1c9a54-2f8e-4a9d-9a6f-1c5d5a2b7e10")


def new_id(entity_name):
    """A server-minted identifier formatted as a UUID, with no type prefix."""
    return str(uuid.uuid5(UUID_NAMESPACE, "%s:%s" % (entity_name, uuid.uuid4().hex)))


class BaseRecord(dict):
    """Dict-backed resource carrying the four system-managed properties."""

    entity_name = "Record"

    def __init__(self, **fields):
        super().__init__()
        now = clock.now()
        self["id"] = new_id(self.entity_name)
        self["created_at"] = format_instant(now)
        self["updated_at"] = format_instant(now)
        self["version"] = 1
        for key, value in fields.items():
            self[key] = value

    # -- mutations ---------------------------------------------------------
    def touch(self):
        """Refresh updated_at and bump the record's own version."""
        self["updated_at"] = format_instant(clock.now())
        self["version"] = int(self.get("version", 0)) + 1

    def set_field(self, key, value, touch=True):
        self[key] = value
        if touch:
            self.touch()

    def refresh_common_from(self, other):
        self["created_at"] = other.get("created_at", self.get("created_at"))
        self["updated_at"] = other.get("updated_at", self.get("updated_at"))
        self["version"] = other.get("version", self.get("version"))


def as_json(record):
    """Serialise a stored record for a response body."""
    return dict(record)


def nearby(entity, code, message=None, http_status=None):
    from errors import ApiError
    raise ApiError(code, message, http_status)