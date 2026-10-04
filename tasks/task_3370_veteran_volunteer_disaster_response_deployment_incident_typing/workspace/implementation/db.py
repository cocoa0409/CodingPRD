"""In-memory data store and logical clock. No persistence of any kind;
a fresh process boot always starts with empty collections and the default clock."""
import uuid
import timeutil
from constants import DEFAULT_CLOCK_ISO

COLLECTIONS = [
    "volunteers", "certifications", "incidents", "operations", "deployments",
    "fob_sites", "duty_shifts", "work_orders", "partners", "courses",
    "enrollments", "wellness_checks",
]

store = {name: {} for name in COLLECTIONS}

_seq = [0]
_clock = [timeutil.parse_iso(DEFAULT_CLOCK_ISO)]


def next_seq():
    _seq[0] += 1
    return _seq[0]


def now():
    return _clock[0]


def now_iso():
    return timeutil.fmt(_clock[0])


def set_clock(dt):
    _clock[0] = dt


def mint(collection, entity):
    """Assign system-managed common fields and insert. Entities start at version 1."""
    entity["id"] = str(uuid.uuid4())
    ts = now_iso()
    entity["created_at"] = ts
    entity["updated_at"] = ts
    entity["version"] = 1
    entity["_seq"] = next_seq()
    store[collection][entity["id"]] = entity
    return entity


def touch(entity):
    """Every modification bumps version and refreshes updated_at (PRD section 2.5)."""
    entity["version"] += 1
    entity["updated_at"] = now_iso()


def get(collection, _id):
    return store[collection].get(_id)


def all_of(collection):
    """All entities in created_at ascending order (creation sequence breaks ties)."""
    return sorted(store[collection].values(), key=lambda e: (e["created_at"], e["_seq"]))
