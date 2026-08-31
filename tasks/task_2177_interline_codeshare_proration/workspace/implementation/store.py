"""In-memory data store, logical clock and row bookkeeping.

The store is empty on every boot: no entity is ever seeded, preloaded or
hardcoded.  Tests build all state through the declared API surface.
"""

import itertools
import re
import uuid
from datetime import datetime, timedelta, timezone

from errors import ApiError

_seq_counter = itertools.count(1)

# Before the clock has ever been set it reads exactly 2026-08-01T00:00:00Z.
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.carriers = {}
        self.agreements = {}
        self.factors = {}
        self.periods = {}
        self.rates = {}
        self.tickets = {}
        self.coupons = {}
        self.runs = {}
        self.invoices = {}
        self.memos = {}
        self.samples = {}
        self.clock = CLOCK_EPOCH


db = Store()


# --------------------------------------------------------------------------
# time helpers
# --------------------------------------------------------------------------

_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d+)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def fmt_dt(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_dt(value):
    """Parse an ISO 8601 datetime; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    frac = m.group(7) or ".0"
    try:
        micro = int(round(float(frac) * 1000000))
    except ValueError:
        return None
    if micro >= 1000000:
        micro = 999999
    try:
        base = datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)), micro,
            tzinfo=timezone.utc,
        )
    except ValueError:
        return None
    tz = m.group(8)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        tz = tz[1:].replace(":", "")
        offset = timedelta(hours=int(tz[:2]), minutes=int(tz[2:4]))
        base = base - sign * offset
    return base


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date; returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)),
                        tzinfo=timezone.utc).date()
    except ValueError:
        return None


def now():
    """Real wall-clock instant, used only for created_at / updated_at."""
    return datetime.now(timezone.utc)


def now_iso():
    return fmt_dt(now())


def clock():
    return db.clock


def clock_iso():
    return fmt_dt(db.clock)


# --------------------------------------------------------------------------
# row helpers
# --------------------------------------------------------------------------

def next_seq():
    return next(_seq_counter)


def new_row(fields, versioned=True):
    row = {"id": str(uuid.uuid4())}
    row.update(fields)
    stamp = now_iso()
    row["created_at"] = stamp
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row["_seq"] = next_seq()
    return row


def touch(row):
    """Register a mutation: bump version and refresh updated_at."""
    row["version"] = row.get("version", 1) + 1
    row["updated_at"] = now_iso()
    return row


def serialize(row):
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def ordered(rows):
    """Collections are always ordered by created_at ascending."""
    return sorted(rows, key=lambda r: r["_seq"])


# --------------------------------------------------------------------------
# lookups
# --------------------------------------------------------------------------

_COLLECTIONS = {
    "carrier": ("carriers", "ERR_CARRIER_NOT_FOUND"),
    "agreement": ("agreements", "ERR_AGREEMENT_NOT_FOUND"),
    "ticket": ("tickets", "ERR_TICKET_NOT_FOUND"),
    "coupon": ("coupons", "ERR_COUPON_NOT_FOUND"),
    "period": ("periods", "ERR_PERIOD_NOT_FOUND"),
    "invoice": ("invoices", "ERR_INVOICE_NOT_FOUND"),
    "memo": ("memos", "ERR_MEMO_NOT_FOUND"),
    "sample": ("samples", "ERR_SAMPLE_NOT_FOUND"),
}


def find(kind, row_id):
    attr, _ = _COLLECTIONS[kind]
    if not isinstance(row_id, str):
        return None
    return getattr(db, attr).get(row_id)


def must_find(kind, row_id):
    row = find(kind, row_id)
    if row is None:
        raise ApiError(_COLLECTIONS[kind][1])
    return row
