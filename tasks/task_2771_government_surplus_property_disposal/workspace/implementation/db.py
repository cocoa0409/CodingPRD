"""In-memory data store and the server-side logical clock.

Nothing in here is seeded: every collection starts empty on every boot and all
state is built by callers through the declared endpoints.
"""
import calendar
import threading
import uuid
from datetime import datetime, date, timedelta, timezone

# ---------------------------------------------------------------------------
# Logical clock (PRD 2.4).  Starts at exactly 2026-08-01T00:00:00Z on every
# boot and only ever moves when POST /_clock/set_current_utc says so.  The host
# wall clock is never consulted.
# ---------------------------------------------------------------------------
CLOCK_EPOCH = datetime(2026, 8, 1, 0, 0, 0)

lock = threading.RLock()


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.now = CLOCK_EPOCH
        self._seq = 0
        self.agencies = {}
        self.turn_ins = {}
        self.assets = {}
        self.assessments = {}
        self.cycles = {}
        self.requests = {}
        self.transfer_orders = {}
        self.venues = {}
        self.lots = {}
        self.bidders = {}
        self.bids = {}
        self.invoices = {}
        self.certificates = {}
        self.distributions = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()

COLLECTIONS = {
    "Agency": "agencies",
    "TurnIn": "turn_ins",
    "SurplusAsset": "assets",
    "ConditionAssessment": "assessments",
    "ScreeningCycle": "cycles",
    "ScreeningRequest": "requests",
    "TransferOrder": "transfer_orders",
    "SaleVenue": "venues",
    "AuctionLot": "lots",
    "Bidder": "bidders",
    "Bid": "bids",
    "SaleInvoice": "invoices",
    "ClearanceCertificate": "certificates",
    "ProceedsDistribution": "distributions",
}


# ---------------------------------------------------------------------------
# time helpers
# ---------------------------------------------------------------------------

def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits (PRD 2.2/2.5)."""
    if dt is None:
        return None
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def iso_date(d):
    if d is None:
        return None
    return "%04d-%02d-%02d" % (d.year, d.month, d.day)


def parse_instant(value):
    """Parse an ISO 8601 instant into a naive UTC datetime.  Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    dt = datetime.fromisoformat(text)
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
    return dt


def parse_date(value):
    """Parse a YYYY-MM-DD calendar date.  Raises ValueError."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if len(text) != 10 or text[4] != "-" or text[7] != "-":
        raise ValueError("bad date")
    return date(int(text[0:4]), int(text[5:7]), int(text[8:10]))


def add_days(dt, days):
    """Exact 24-hour multiples (PRD 2.4)."""
    return dt + timedelta(days=days)


def add_months(d, months):
    """Calendar-month arithmetic keeping the day-of-month, clamped down to the
    last valid day of the target month (PRD 2.4)."""
    total = (d.year * 12 + (d.month - 1)) + months
    year = total // 12
    month = total % 12 + 1
    last = calendar.monthrange(year, month)[1]
    day = d.day if d.day <= last else last
    return date(year, month, day)


def today():
    return db.now.date()


# ---------------------------------------------------------------------------
# row helpers
# ---------------------------------------------------------------------------

def new_id():
    return str(uuid.uuid4())


def base_row(with_common=True):
    row = {"id": new_id(), "created_at": iso(db.now), "_seq": db.next_seq()}
    if with_common:
        row["updated_at"] = iso(db.now)
        row["version"] = 1
    return row


class Touched(object):
    """Tracks which rows have already had their version bumped inside the
    current request so that a single operation bumps each row exactly once
    (PRD 2.5 / 2.9)."""

    def __init__(self):
        self.ids = set()

    def touch(self, row):
        if row is None:
            return
        key = id(row)
        if key in self.ids:
            return
        self.ids.add(key)
        if "version" in row:
            row["version"] = row["version"] + 1
        if "updated_at" in row:
            row["updated_at"] = iso(db.now)


def sort_key(row):
    return (row["created_at"], row["_seq"])


def by_created(rows):
    return sorted(rows, key=sort_key)
