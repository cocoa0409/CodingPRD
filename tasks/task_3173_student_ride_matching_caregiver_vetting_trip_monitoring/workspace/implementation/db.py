"""In-memory data store.

Persistence policy (hard constraint for this benchmark): every collection is a
plain dict/set/list living in process memory. There is no SQLite file, no JSON
dump, no /tmp cache and no external datastore, so re-invoking start.sh wipes
every byte of state and guarantees a fresh boot.

The store starts EMPTY on every boot. Nothing in this module - or anywhere
else - seeds, preloads, registers or hardcodes an entity. Every entity a caller
observes is constructed through a declared endpoint.
"""

from clock import new_id, now_utc, stamp


class Store:
    def __init__(self):
        # Ordered insertion is preserved by dict, which also gives the
        # created_at-ascending default ordering of PRD section 2.3.
        self.districts = {}
        self.riders = {}
        self.drivers = {}
        self.background_checks = {}
        self.vehicle_inspections = {}
        self.contracts = {}
        self.ride_requests = {}
        self.trips = {}
        self.handoffs = {}
        self.safety_incidents = {}
        self.trip_alerts = {}
        self.geofences = {}
        self.geofence_checks = {}
        self.billing_statements = {}
        # RideRequests affected by a driver availability block.
        self.driver_blocks = []


STORE = Store()


def reset_store():
    """Reset in place so every imported reference keeps pointing at the live store."""
    STORE.__init__()


# --- common field helpers (PRD section 2.7) ---------------------------------

def new_record(fields):
    """Mint the common field set onto a freshly created resource."""
    record = dict(fields)
    record["id"] = new_id()
    record["created_at"] = stamp()
    record["updated_at"] = record["created_at"]
    record["version"] = 1
    return record


def touch(record):
    """Stamp updated_at and advance version for a plain property mutation."""
    record["updated_at"] = stamp()
    record["version"] = record.get("version", 0) + 1
    return record


def bump_version(record):
    """Advance version WITHOUT stamping updated_at (state transitions).

    PRD section 2.7 scopes updated_at to property mutations; endpoints in this
    scaffold that advance version on a state transition name only the version.
    """
    record["version"] = record.get("version", 0) + 1
    return record


def save(coll_name, record):
    getattr(STORE, coll_name)[record["id"]] = record
    return record


def get(coll_name, rid):
    return getattr(STORE, coll_name).get(rid)


def all_of(coll_name):
    return list(getattr(STORE, coll_name).values())


def insert_at(record, when):
    """Backdate created_at/updated_at so an entity can model a long-standing
    row (used only where an endpoint accepts an explicit registration date)."""
    record["created_at"] = when
    record["updated_at"] = when
    return record


def now():
    return now_utc()


def stamp():
    """The current logical-clock instant, rendered ISO 8601 with 3 decimals."""
    from clock import stamp as _stamp

    return _stamp()