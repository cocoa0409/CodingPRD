"""In-memory data store. Empty on every boot; nothing is seeded or preloaded."""

import uuid
from datetime import datetime, timezone

# Logical clock default (PRD section 2.5 / 3.10).
CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

_HOSTS = "hosts"
_SITES = "sites"
_MEMBERS = "members"
_VEHICLES = "vehicles"
_WINDOWS = "windows"
_STAYS = "stays"
_REVIEWS = "reviews"
_INCIDENTS = "incidents"
_RECORDS = "records"
_DISPOSITIONS = "dispositions"

# Insertion-ordered dicts; every lookup is by id and every list is walked in
# insertion order, which is creation order (created_at ascending).
TABLES = {
    _HOSTS: {},
    _SITES: {},
    _MEMBERS: {},
    _VEHICLES: {},
    _WINDOWS: {},
    _STAYS: {},
    _REVIEWS: {},
    _INCIDENTS: {},
    _RECORDS: {},
    _DISPOSITIONS: {},
}

_clock = {"now": CLOCK_START}


def reset():
    """Wipe every table and restore the logical clock to its boot instant."""
    for table in TABLES.values():
        table.clear()
    _clock["now"] = CLOCK_START


def now():
    """The current logical clock instant."""
    return _clock["now"]


def set_clock(instant):
    _clock["now"] = instant


def new_id():
    return str(uuid.uuid4())


def table(name):
    return TABLES[name]


def add(name, obj):
    TABLES[name][obj["id"]] = obj
    return obj


def get(name, obj_id):
    return TABLES[name].get(obj_id)


def all_of(name):
    return list(TABLES[name].values())


def stamp(obj):
    """Refresh updated_at and bump version -- recomputation counts as mutation."""
    instant = now()
    obj["updated_at"] = instant
    obj["version"] = obj.get("version", 0) + 1
    return obj


def create_common():
    """The three system bookkeeping fields for a freshly created resource."""
    instant = now()
    return {"created_at": instant, "updated_at": instant, "version": 1}


# Table name accessors used across the service layer.
HOSTS = _HOSTS
SITES = _SITES
MEMBERS = _MEMBERS
VEHICLES = _VEHICLES
WINDOWS = _WINDOWS
STAYS = _STAYS
REVIEWS = _REVIEWS
INCIDENTS = _INCIDENTS
RECORDS = _RECORDS
DISPOSITIONS = _DISPOSITIONS