"""In-memory storage for the fractional collectible securitization API.

No persistence of any kind: every dict starts empty on each process boot and
every entity is created through the declared API surface.
"""
import uuid
from datetime import datetime, timezone, timedelta

CLOCK_DEFAULT = "2026-09-01T00:00:00Z"


def parse_dt(value):
    """Parse an ISO 8601 instant into an aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC. Sub-second precision is preserved when present, but an
    instant that lands exactly on a whole second — which is every instant the
    logical clock yields while it is held still — is written without a
    fractional part (`2026-09-01T00:00:00Z`)."""
    if dt is None:
        return None
    if isinstance(dt, str):
        dt = parse_dt(dt)
    dt = dt.astimezone(timezone.utc)
    if dt.microsecond:
        return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def to_ms(dt):
    """Truncate a datetime to millisecond precision (matches the wire format)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.replace(microsecond=(dt.microsecond // 1000) * 1000)


def day_exact(dt):
    """Round-trip a datetime through the millisecond wire format."""
    return to_ms(dt)


class Store:
    def __init__(self):
        self.clock = parse_dt(CLOCK_DEFAULT)
        self.artists = {}
        self.investors = {}
        self.artworks = {}
        self.asset_reports = {}
        self.appraisals = {}
        self.offerings = {}
        self.subscriptions = {}
        self.custody_records = {}
        self.holding_decisions = {}
        self.transfer_orders = {}
        self.lots = {}
        self.insurance_policies = {}
        self.offering_reports = {}
        self.fee_accruals = {}
        self.distributions = {}
        self.platform_accounts = {}
        self.quotes = {}
        self.order = []          # (kind, id) monotone insertion order
        self.order_index = {}    # id -> monotone insertion index
        self.seq = 0             # monotone creation sequence

    # -- clock -------------------------------------------------------------
    def now(self):
        return self.clock

    def advance(self, dt):
        self.clock = dt

    # -- ids ---------------------------------------------------------------
    def new_id(self):
        return str(uuid.uuid4())

    def next_seq(self):
        self.seq += 1
        return self.seq

    def register(self, kind, obj):
        obj["id"] = self.new_id()
        obj["created_at"] = to_ms(self.now())
        self.order.append((kind, obj["id"]))
        self.order_index[obj["id"]] = len(self.order)
        return obj

    def ordered(self, table, predicate=None):
        """table is the name of one of this store's tables; rows come back in
        monotone insertion order (which is stable across same-clock writes)."""
        name = table
        if not isinstance(table, str):
            name = None
            for attr, value in vars(self).items():
                if value is table:
                    name = attr
                    break
            if name is None:
                return []
        table = getattr(self, name)
        rows = []
        for kind, oid in self.order:
            if kind == name:
                obj = table.get(oid)
                if obj is not None and (predicate is None or predicate(obj)):
                    rows.append(obj)
        return rows


DB = Store()


def new_row(extra=None):
    row = {}
    if extra:
        row.update(extra)
    return row


def touch(row):
    row["updated_at"] = to_ms(DB.now())
    row["version"] = int(row.get("version") or 1) + 1
    return row


def add_days(dt, days):
    return to_ms(dt + timedelta(days=days)) if dt is not None else None