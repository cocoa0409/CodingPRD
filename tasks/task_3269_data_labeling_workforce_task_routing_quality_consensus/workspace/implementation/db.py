"""In-memory store for the Data Labeling Ops API.

Storage is plain Python dictionaries keyed by id. Nothing is written to disk and
nothing is seeded: every table below starts empty on every process boot, and
`start.sh` handing off to a fresh `python3 app.py` is therefore guaranteed to
wipe every byte of state. All entities are created through the API surface.

The logical clock of PRD section 2.9 is also held here. It starts at exactly
2026-09-01T00:00:00Z and only ever moves when a PlatformAdmin supplies a new
instant; the server never falls back to wall-clock time.
"""

import uuid
from datetime import datetime, timedelta, timezone

# --------------------------------------------------------------------------
# Tables (all empty at boot)
# --------------------------------------------------------------------------
programs = {}
spec_units = {}
items = {}
commits = {}
workers = {}
qualifications = {}
incidents = {}
appeals = {}
week_epochs = {}

# Appends only, for entity creation.
_creation_order = []

CLOCK_START = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
clock = {"now": CLOCK_START}

# --------------------------------------------------------------------------
# Clock helpers
# --------------------------------------------------------------------------
ISO_FMT = "%Y-%m-%dT%H:%M:%S.%f"


def now():
    """The current logical clock instant."""
    return clock["now"]


def set_clock(dt):
    clock["now"] = dt


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD section 2.7)."""
    if dt is None:
        return None
    return dt.astimezone(timezone.utc).strftime(ISO_FMT)[:-3] + "Z"


def parse_dt(value):
    """Parse an ISO 8601 instant; accepts a trailing Z and both .fff and .ffffff."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def elapsed_seconds(start, end=None):
    """Whole seconds between two logical instants."""
    if start is None:
        return 0
    end = end or now()
    return int((end - start).total_seconds())


def add_seconds(base, seconds):
    return base + timedelta(seconds=seconds)


# --------------------------------------------------------------------------
# Identifier minting
# --------------------------------------------------------------------------
def new_id():
    """A UUID string with no type prefix embedded in it (PRD section 2.7)."""
    return str(uuid.uuid4())


# --------------------------------------------------------------------------
# Common fields (PRD section 2.7)
# --------------------------------------------------------------------------
def seal(record):
    """Mint id/created_at/updated_at/version and register creation order."""
    record["id"] = new_id()
    stamp = now()
    record["created_at"] = stamp
    record["updated_at"] = stamp
    record["version"] = 1
    _creation_order.append(record)
    return record


def touch(record):
    """A mutation of a resource refreshes updated_at and increments version."""
    record["updated_at"] = now()
    record["version"] = int(record.get("version", 0)) + 1
    return record


def bump_extra(record):
    """Explicit `version incremented by 1` where §3 also names it."""
    return touch(record)


def creation_seq(record):
    """Monotonic creation order, used for the default list ordering."""
    try:
        return _creation_order.index(record)
    except ValueError:
        return 0


# --------------------------------------------------------------------------
# Deterministic lookup helpers
# --------------------------------------------------------------------------
def unit_of_item(item):
    return spec_units.get(item.get("spec_unit_id"))


def program_of_unit(unit):
    if unit is None:
        return None
    return programs.get(unit.get("program_id"))


def program_of_item(item):
    return program_of_unit(unit_of_item(item))


def parent_of_unit(unit):
    return program_of_unit(unit)


def commits_of_item(item_id):
    return [c for c in commits.values() if c.get("item_id") == item_id]


def items_of_unit(unit_id):
    return [i for i in items.values() if i.get("spec_unit_id") == unit_id]


def units_of_program(program_id):
    return [u for u in spec_units.values() if u.get("program_id") == program_id]


def qualifications_of_worker(worker_id):
    return [q for q in qualifications.values() if q.get("worker_id") == worker_id]


def incidents_of_worker(worker_id):
    return [i for i in incidents.values() if i.get("worker_id") == worker_id]


def incidents_of_program(program_id):
    return [i for i in incidents.values() if i.get("program_id") == program_id]


def open_epoch():
    """The single OPEN WeekEpoch row; created lazily from the clock (PRD §2.9)."""
    for epoch in week_epochs.values():
        if epoch.get("status") == "OPEN":
            return epoch
    record = {
        "index": 0,
        "name": None,
        "starts_at_utc": now(),
        "status": "OPEN",
    }
    seal(record)
    week_epochs[record["id"]] = record
    return record


def current_epoch_index():
    return int(open_epoch().get("index", 0))