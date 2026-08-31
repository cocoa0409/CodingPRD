"""In-memory data store, the logical clock and low level row helpers."""
import threading
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

UTC = timezone.utc
CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

COLLECTIONS = (
    "funds",
    "employers",
    "participants",
    "reports",
    "lines",
    "assessments",
    "audits",
    "coverage_months",
    "accruals",
    "withdrawals",
    "installments",
    "trustees",
    "motions",
    "votes",
    "transfers",
)


class Store(object):
    def __init__(self):
        self.lock = threading.RLock()
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = CLOCK_DEFAULT
        self._seq = 0

    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- clock ---------------------------------------------------------
    @property
    def now(self):
        return self.clock

    @property
    def today(self):
        return self.clock.date()

    @property
    def clock_month(self):
        return self.clock.strftime("%Y-%m")


db = Store()


# ---------------------------------------------------------------------
# formatting helpers
# ---------------------------------------------------------------------
def iso_ts(dt):
    if dt is None:
        return None
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def iso_date(d):
    if d is None:
        return None
    return d.isoformat()


def new_id():
    return str(uuid.uuid4())


def new_row(collection, fields, common=True):
    row = dict(fields)
    row["id"] = new_id()
    row["created_at"] = db.now
    row["_seq"] = db.next_seq()
    if common:
        row["updated_at"] = db.now
        row["version"] = 1
    collection[row["id"]] = row
    return row


def touch(row):
    """Refresh updated_at and bump the version counter of a mutated row."""
    if row is None or "version" not in row:
        return row
    row["updated_at"] = db.now
    row["version"] = row["version"] + 1
    return row


def order_key(row):
    """Default list ordering: created_at ASC, insertion order as tie-break."""
    return (row["created_at"], row["_seq"])


def sorted_rows(rows):
    return sorted(rows, key=order_key)


def values(collection):
    return list(collection.values())


# ---------------------------------------------------------------------
# month-key helpers
# ---------------------------------------------------------------------
def parse_month(key):
    y, m = key.split("-")
    return int(y), int(m)


def month_index(key):
    y, m = parse_month(key)
    return y * 12 + (m - 1)


def month_from_index(idx):
    return "%04d-%02d" % (idx // 12, idx % 12 + 1)


def month_add(key, n):
    return month_from_index(month_index(key) + n)


def valid_month_key(value):
    if not isinstance(value, str) or len(value) != 7 or value[4] != "-":
        return False
    y, sep, m = value[:4], value[4], value[5:]
    if not (y.isdigit() and m.isdigit()):
        return False
    return 1 <= int(m) <= 12


def date_from_iso(text):
    return datetime.strptime(text, "%Y-%m-%d").date()


def plan_year_of(month_key_str, plan_year_start_month):
    y, m = parse_month(month_key_str)
    if plan_year_start_month == 1:
        return y
    return y if m >= plan_year_start_month else y - 1


def plan_year_end_date(plan_year, plan_year_start_month):
    from datetime import date

    nxt = date(plan_year + 1, plan_year_start_month, 1)
    return nxt - timedelta(days=1)


def plan_year_months(plan_year, plan_year_start_month):
    start = "%04d-%02d" % (plan_year, plan_year_start_month)
    return [month_add(start, i) for i in range(12)]


D0 = Decimal("0")
