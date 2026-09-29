"""In-memory store.  Starts completely empty on every boot; nothing is seeded."""

from datetime import datetime, timezone

from util import new_id, next_seq, utcnow

# The logical clock's default value.  Every timestamp the service stamps itself
# for domain purposes (suppressed_at, mailed_at, finalized_at) and every temporal
# rule (fatigue decay, in-home spacing, matchback windows) reads this clock.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.seasons = {}
        self.segments = {}
        self.rentals = {}
        self.merge_purge_runs = {}
        self.plans = {}
        self.drops = {}
        self.lines = {}
        self.placements = {}
        self.batches = {}
        self.contact_events = {}
        self.suppression_rules = {}
        self.test_cells = {}
        self.matchback_runs = {}
        self.online_orders = {}
        self.clock = DEFAULT_CLOCK


db = Store()


def now():
    """The logical clock's current value."""
    return db.clock


def new_row(with_version=True):
    stamp = utcnow()
    row = {"id": new_id(), "created_at": stamp, "_seq": next_seq()}
    if with_version:
        row["updated_at"] = stamp
        row["version"] = 1
    return row


def touch(row):
    """Advance a row's concurrency version by exactly one and refresh updated_at."""
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = utcnow()


def apply_changes(row, updates):
    """Write derived fields; report whether anything actually moved."""
    changed = False
    for key, value in updates.items():
        if row.get(key) != value:
            row[key] = value
            changed = True
    return changed


def by_created(rows, reverse=False):
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]), reverse=reverse)


def rows(table):
    return by_created(list(table.values()))
