"""In-memory data store, logical broadcast clock, and record helpers.

PRD 2.4  — every resource carries id / created_at / updated_at / version.
PRD 2.5  — nothing reads the host machine's wall clock; the logical clock
           starts at exactly 2026-08-01T00:00:00Z.
The store starts empty on every boot: no entity is ever seeded here.
"""

import itertools
import random
import string
import uuid
from datetime import datetime, timezone

# PRD 2.5: "That clock starts at exactly 2026-08-01T00:00:00Z".
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)
        # PRD 2.4 lists exactly thirteen resources.
        self.hosts = {}
        self.products = {}
        self.viewers = {}
        self.shows = {}
        self.channels = {}
        self.bookings = {}
        self.slots = {}
        self.offers = {}
        self.disclosures = {}
        self.carts = {}
        self.cart_items = {}
        self.orders = {}
        self.interactions = {}

    def next_seq(self):
        return next(self._seq)


db = Store()


def now():
    """The logical broadcast clock (PRD 2.5)."""
    return db.clock


def set_clock(value):
    previous = db.clock
    db.clock = value
    return previous


def new_id():
    # PRD 2.4: a bare server-minted UUID string, no type prefix.
    return str(uuid.uuid4())


def fmt_dt(value):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if value is None:
        return None
    value = value.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        value.year, value.month, value.day,
        value.hour, value.minute, value.second,
        value.microsecond // 1000,
    )


def wall_now_iso():
    return fmt_dt(datetime.now(timezone.utc))


def new_record():
    """Common fields at creation: version starts at 1, updated_at == created_at."""
    stamp = now()
    return {
        "id": new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_seq": db.next_seq(),
    }


def touch(record):
    """PRD 2.4: version increments by exactly 1 on every mutation, and
    updated_at is refreshed to the same logical instant."""
    record["version"] += 1
    record["updated_at"] = now()


def by_created(rows):
    """PRD 2.3: results sorted by created_at ascending (oldest first)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def common_out(record):
    return {
        "id": record["id"],
        "created_at": fmt_dt(record["created_at"]),
        "updated_at": fmt_dt(record["updated_at"]),
        "version": record["version"],
    }
