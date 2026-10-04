"""In-memory data store. Fresh process boots with zero entity state."""

import itertools
import itertools
import uuid
from datetime import datetime, timezone

_SEQ = itertools.count(1)

_SEQ = itertools.count(1)


def new_id():
    return str(uuid.uuid4())


def iso_now_wall():
    """Wall-clock timestamp for envelope meta (3 fractional digits, UTC)."""
    now = datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def iso_from_dt(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


class Store:
    def __init__(self):
        self.clubs = {}
        self.members = {}
        self.catalog_items = {}
        self.offers = {}
        self.sessions = {}
        self.scan_lines = {}
        self.intercepts = {}
        self.exit_verifications = {}
        self.lp_cases = {}
        self.curbside_orders = {}
        # Logical clock: starts exactly at 2026-09-01T00:00:00Z; never wall-clock.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self.clock


STORE = Store()


def touch(entity):
    """Refresh updated_at and bump version on a mutated entity."""
    entity["updated_at"] = iso_from_dt(STORE.now())
    entity["version"] = entity.get("version", 1) + 1


def new_entity():
    ts = iso_from_dt(STORE.now())
    return {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next(_SEQ),
    }
