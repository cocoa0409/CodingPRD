"""In-memory data store.

Everything lives in process memory: there is no file, no cache and no external
persistence of any kind, so re-invoking start.sh yields a byte-for-byte clean
boot.  No entity is seeded at import time or at boot: every record is created
by a caller through a declared endpoint.
"""

import uuid

from timeutil import DEFAULT_CLOCK, UTC, fmt_ts, parse_ts

# Stable enum orderings used by computed fields.
PRODUCT_LINE_ORDER = ["LENDING", "BANKING", "INVESTING", "CAREER"]
TIER_ORDER = ["NONE", "BASE", "PLUS", "PREMIER"]


class Store(object):
    """Dict-of-dicts container keyed by entity id, plus the logical clock."""

    COLLECTIONS = (
        "members",
        "holdings",
        "loan_accounts",
        "enrollments",
        "entitlements",
        "rules",
        "applications",
        "ledger",
        "cycles",
        "notices",
        "sessions",
        "checks",
        "deposit_postings",
    )

    def __init__(self):
        for name in self.COLLECTIONS:
            setattr(self, name, {})
        self.logical_clock = parse_ts(DEFAULT_CLOCK)
        self.request_seq = 0

    # -- identity ---------------------------------------------------------
    def next_id(self):
        return str(uuid.uuid4())

    def next_request_id(self):
        self.request_seq += 1
        return "req_%s%06d" % (uuid.uuid4().hex[:10].upper(), self.request_seq)

    # -- clock ------------------------------------------------------------
    def clock(self):
        return self.logical_clock

    def clock_iso(self):
        return fmt_ts(self.logical_clock)

    def set_clock(self, value):
        parsed = parse_ts(value)
        if parsed is None:
            return None
        self.logical_clock = parsed
        return parsed

    # -- generic helpers --------------------------------------------------
    def get(self, collection, entity_id):
        if entity_id is None:
            return None
        return getattr(self, collection).get(entity_id)

    def put(self, collection, entity):
        getattr(self, collection)[entity["id"]] = entity
        return entity

    def all(self, collection):
        return list(getattr(self, collection).values())


DB = Store()


def stamp_create(entity, now):
    """Apply the four system-managed common fields at creation time."""
    entity["created_at"] = fmt_ts(now)
    entity["updated_at"] = fmt_ts(now)
    entity["version"] = 1
    return entity


def touch(entity, now, bump=True):
    """Refresh updated_at and advance version on every mutation."""
    entity["updated_at"] = fmt_ts(now)
    if bump:
        entity["version"] = int(entity.get("version", 1)) + 1
    return entity


def touch_soft(entity, now):
    """Refresh updated_at without advancing version (non-entity metadata rows)."""
    entity["updated_at"] = fmt_ts(now)
    return entity


def created_key(entity):
    """Sort key placing records in creation order, oldest first."""
    return (entity.get("created_at") or "", entity.get("id") or "")


def parse_dt(entity, field):
    return parse_ts(entity.get(field))


def now_dt():
    return DB.clock()


def utc_now():
    return DB.clock()


__all__ = [
    "DB",
    "Store",
    "UTC",
    "stamp_create",
    "touch",
    "touch_soft",
    "created_key",
    "parse_dt",
    "now_dt",
    "utc_now",
    "PRODUCT_LINE_ORDER",
    "TIER_ORDER",
]