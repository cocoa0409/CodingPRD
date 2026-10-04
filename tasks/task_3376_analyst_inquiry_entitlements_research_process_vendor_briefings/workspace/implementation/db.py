"""In-memory data store and the logical clock.

The store starts empty on every boot: no entity is seeded, preloaded or
hardcoded.  Every record a caller needs is built through the declared API.
State lives in plain dicts keyed by id and is discarded when the process exits.
"""

import copy
import uuid
from datetime import datetime

from timeutil import format_dt, format_dt_seconds, parse_dt

# The server's startup default is exactly this instant and never falls back to
# wall-clock time (PRD 2.4).
CLOCK_DEFAULT = "2026-09-01T00:00:00Z"


class Store:
    def __init__(self):
        self.reset()

    def reset(self):
        self.clients = {}
        self.seats = {}
        self.analysts = {}
        self.inquiries = {}
        self.documents = {}
        self.vendors = {}
        self.inclusions = {}
        self.briefings = {}
        self.sales_relationships = {}
        self.events = {}
        self.sponsorships = {}
        self.current_utc = parse_dt(CLOCK_DEFAULT)

    # -- logical clock ------------------------------------------------------
    def now(self):
        return self.current_utc

    def now_str(self):
        return format_dt(self.current_utc)

    def set_clock(self, dt):
        self.current_utc = dt

    # -- generic entity plumbing -------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def create(self, **fields):
        """Mint a resource with the four system-managed properties (PRD 2.10)."""
        stamp = self.now_str()
        obj = {
            "id": self.new_id(),
            "created_at": stamp,
            "updated_at": stamp,
            "version": 1,
        }
        obj.update(fields)
        return obj

    def touch(self, obj):
        """Refresh updated_at and bump version after a modification."""
        obj["updated_at"] = self.now_str()
        obj["version"] = obj.get("version", 1) + 1
        return obj


db = Store()


def set_fields(obj, **values):
    """Assign fields, returning True when at least one value actually changed."""
    changed = False
    for key, value in values.items():
        if obj.get(key, _MISSING) != value:
            obj[key] = value
            changed = True
    return changed


class _Missing:
    pass


_MISSING = _Missing()


def serialize(obj):
    """Return the public JSON view: drop private keys, render datetimes."""
    return _clean(copy.deepcopy(obj))


def serialize_list(items):
    return [serialize(item) for item in items]


def _clean(value):
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items() if not k.startswith("_")}
    if isinstance(value, list):
        return [_clean(v) for v in value]
    if isinstance(value, datetime):
        # Lifecycle instants default to second precision (PRD 2.8); only
        # created_at / updated_at / api_request_timestamp carry fractional digits.
        return format_dt_seconds(value)
    return value
