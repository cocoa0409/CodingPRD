"""In-memory data store and logical clock for the FHA MI endorsement platform.

The store starts empty on every boot. No seeding of any kind.
"""
import threading
import uuid
from datetime import datetime, timezone


class DB:
    def __init__(self):
        self.lock = threading.RLock()
        self.lenders = {}
        self.filings = {}
        self.cases = {}
        self.appraisals = {}
        self.escrows = {}
        self.mip_entries = {}
        self.reviews = {}
        self.defects = {}
        self.agreements = {}
        self.actions = {}
        self.claims = {}
        # Logical clock: startup default is exactly 2026-09-01T00:00:00Z.
        self.clock = datetime(2026, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        self.seq = 0


db = DB()


def new_id():
    return str(uuid.uuid4())


def _wall_now():
    return datetime.now(timezone.utc)


def iso_millis(dt):
    """ISO 8601 UTC timestamp with exactly three fractional digits."""
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def stamp_now():
    """created_at / updated_at: wall-clock UTC, three fractional digits."""
    return iso_millis(_wall_now())


def next_seq():
    db.seq += 1
    return db.seq


def make_entity(fields):
    ts = stamp_now()
    e = {
        "id": new_id(),
        "created_at": ts,
        "updated_at": ts,
        "version": 1,
        "_seq": next_seq(),
    }
    e.update(fields)
    return e


def bump(e):
    """Increment the entity's own version by 1 and refresh updated_at."""
    e["version"] += 1
    e["updated_at"] = stamp_now()


def iso_clock(dt):
    """Canonical rendering of a logical-clock instant."""
    if dt.microsecond:
        return iso_millis(dt)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def logical_now():
    return db.clock


def logical_date():
    return db.clock.date()


def public(e):
    return {k: v for k, v in e.items() if not k.startswith("_")}
