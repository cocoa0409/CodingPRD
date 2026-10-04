"""In-memory data store, logical clock, identity/timestamp helpers.

The store starts completely empty on every boot; state is built exclusively
via API calls. No seeding, no disk persistence.
"""
import itertools
import uuid
from datetime import datetime, timezone
from decimal import Decimal

# Entity collections keyed by id. All start empty.
db = {
    "farmers": {},
    "elevators": {},
    "schedules": {},
    "programs": {},
    "quotes": {},
    "plants": {},
    "buyers": {},
    "contracts": {},
    "tickets": {},
    "positions": {},
    "lanes": {},
    "shipments": {},
    "runs": {},
    "hedges": {},
    "sales": {},
}

# Internal monotonic sequence used as a created_at tie-breaker.
_seq = itertools.count(1)

DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"
_clock = {"current": None}


def init_clock():
    from dates import parse_iso
    _clock["current"] = parse_iso(DEFAULT_CLOCK_ISO)


def get_clock():
    return _clock["current"]


def set_clock(dt):
    _clock["current"] = dt


def next_seq():
    return next(_seq)


def new_id():
    return str(uuid.uuid4())


def wall_now():
    return datetime.now(timezone.utc)


def iso3(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def stamp_new(rec):
    """Assign common fields on creation: created_at/updated_at/version."""
    rec["created_at"] = iso3(wall_now())
    rec["updated_at"] = rec["created_at"]
    rec["version"] = 1
    rec["_seq"] = next_seq()


def stamp_append_only(rec):
    """MarketQuote: id + created_at only (no updated_at/version)."""
    rec["created_at"] = iso3(wall_now())
    rec["_seq"] = next_seq()


def touch(rec):
    """Every mutation refreshes updated_at and increments version by one."""
    rec["updated_at"] = iso3(wall_now())
    rec["version"] = int(rec.get("version", 1)) + 1


def to_jsonable(v):
    """Recursively convert a record to its JSON view: drop _-internal keys,
    Decimals become numbers, datetimes become iso3 strings."""
    if isinstance(v, dict):
        return {k: to_jsonable(val) for k, val in v.items() if not k.startswith("_")}
    if isinstance(v, (list, tuple)):
        return [to_jsonable(x) for x in v]
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, datetime):
        return iso3(v)
    return v


init_clock()
