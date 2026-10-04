"""In-memory data store + logical clock. State resets on every process boot."""
import uuid
from datetime import datetime, timezone

DEFAULT_CLOCK = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

db = {
    "products": {},
    "orders": {},
    "melts": {},
    "molds": {},
    "units": {},
    "reports": {},
    "seasoning": {},
    "permits": {},
    "readings": {},
    "inventory": {},
    "allocations": {},
    "outlet_sales": {},
}

_clock = {"now": DEFAULT_CLOCK}
_seq = {"n": 0}


def now():
    return _clock["now"]


def set_now(dt):
    _clock["now"] = dt


def format_dt(dt):
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso():
    return format_dt(now())


def new_id():
    return str(uuid.uuid4())


def next_seq():
    _seq["n"] += 1
    return _seq["n"]


def make_entity():
    """Entity with the common fields: id, created_at, updated_at, version."""
    ts = iso()
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }


def make_leaf():
    """Entity without common fields (EmissionsReading, OutletSale): id + created_at only."""
    return {"id": new_id(), "created_at": iso(), "_seq": next_seq()}


def touch(ent):
    ent["version"] += 1
    ent["updated_at"] = iso()


def sort_key(e):
    return (e["created_at"], e["_seq"])
