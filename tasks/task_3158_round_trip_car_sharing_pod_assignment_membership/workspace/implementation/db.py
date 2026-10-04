"""In-memory data store, logical clock and common-field plumbing.

Storage is deliberately process-local: every collection is a plain dict keyed by
id. Nothing is ever persisted, so a fresh `start.sh` invocation starts from a
completely empty world (PRD §2.8: the server mints every entity; the store owns
no seed data).
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# PRD §2.7: the clock's value at server startup is exactly this instant and it
# never falls back to real wall-clock time.
DEFAULT_CLOCK = "2026-09-01T00:00:00.000Z"

COMMON_ORDER_TIEBREAK = "created_at ASC then insertion order"


def parse_ts(value):
    """Parse an ISO 8601 instant (optionally Z-suffixed) into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    """Format a datetime as ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def whole_minutes(later, earlier):
    """Whole minutes between two instants, floored at zero (PRD §3.8/§3.9)."""
    delta = (parse_ts(later) - parse_ts(earlier)).total_seconds()
    if delta <= 0:
        return 0
    return int(delta) // 60


def round_half_up(value, places=0):
    q = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(q, rounding=ROUND_HALF_UP)


def to_int_round_half_up(value):
    return int(round_half_up(value, 0))


class Store:
    """Every collection is a dict keyed by server-minted id."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.members = {}
        self.accounts = {}
        self.memberships = {}
        self.pods = {}
        self.vehicles = {}
        self.reservations = {}
        self.incidents = {}
        self.maintenance_orders = {}
        self.access_events = {}
        self.fuel_transactions = {}
        self.community_signals = {}
        self.driving_reports = {}
        self.tier_entitlements = {}
        self.shift_bundles = {}
        self.citations = {}
        self.payments = {}
        self._seq = 0
        self.clock = parse_ts(DEFAULT_CLOCK)

    # ---- clock -----------------------------------------------------------
    def now(self):
        return self.clock

    def now_iso(self):
        return fmt_ts(self.clock)

    def set_clock(self, iso_text):
        self.clock = parse_ts(iso_text)
        return self.clock

    def shift(self, **kwargs):
        return self.clock + timedelta(**kwargs)

    # ---- identifiers -----------------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    @staticmethod
    def new_id():
        return str(uuid.uuid4())

    # ---- row plumbing ----------------------------------------------------
    def create(self, collection, **fields):
        seq = self.next_seq()
        now = self.now_iso()
        row = {
            "id": self.new_id(),
            "created_at": now,
            "updated_at": now,
            "version": 1,
            "_seq": seq,
        }
        row.update(fields)
        collection[row["id"]] = row
        return row

    def touch(self, row):
        """Refresh updated_at for a derived-field recompute (PRD §2.8)."""
        row["updated_at"] = self.now_iso()

    def bump(self, row):
        """A mutation of the row: version increments by one, updated_at refreshes."""
        row["version"] += 1
        row["updated_at"] = self.now_iso()
        return row


def serialize(row):
    """Public view of a row: internal keys are stripped."""
    if row is None:
        return None
    return {k: v for k, v in row.items() if not k.startswith("_")}


def ordered(rows):
    """List ordering: creation timestamp ascending, ties by insertion order (PRD §2.3)."""
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))


def paginate(rows, limit, offset):
    total = len(rows)
    page = rows[offset: offset + limit]
    return page, {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }


STORE = Store()