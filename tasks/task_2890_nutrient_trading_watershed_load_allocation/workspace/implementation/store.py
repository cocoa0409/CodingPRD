"""In-memory data store, logical program clock and row bookkeeping.

The store starts completely empty on every boot.  Nothing is seeded, preloaded
or hardcoded: every row is created through the declared API surface.
"""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

# The logical clock's value before it has ever been set.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

COLLECTIONS = (
    "watersheds",
    "reaches",
    "tmdl_assessments",
    "source_assessments",
    "allocation_runs",
    "permits",
    "producers",
    "practice_projects",
    "verification_events",
    "credit_batches",
    "credit_transactions",
    "monitoring_samples",
    "adaptive_reviews",
)


class Store(object):
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        for name in COLLECTIONS:
            setattr(self, name, {})

    def next_seq(self):
        self._seq += 1
        return self._seq

    def new_id(self):
        return str(uuid.uuid4())


db = Store()


# --------------------------------------------------------------------------
# logical clock helpers
# --------------------------------------------------------------------------
def now():
    return db.clock


def iso(dt):
    """ISO 8601 UTC with exactly three fractional-second digits."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def now_iso():
    return iso(db.clock)


def today():
    return db.clock.astimezone(timezone.utc).date()


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(?:\.(\d{1,6})\d*)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_datetime(value):
    """Parse an ISO 8601 instant.  Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    offset = timezone.utc
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timezone(sign * timedelta(hours=int(body[:2]), minutes=int(body[2:4])))
    try:
        return datetime(year, month, day, hour, minute, second, micro, tzinfo=offset).astimezone(
            timezone.utc
        )
    except ValueError:
        return None


_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_date(value):
    if not isinstance(value, str):
        return None
    m = _DATE_RE.match(value.strip())
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def day_start(d):
    return datetime(d.year, d.month, d.day, 0, 0, 0, 0, tzinfo=timezone.utc)


def day_end(d):
    return datetime(d.year, d.month, d.day, 23, 59, 59, 999000, tzinfo=timezone.utc)


def plus_years(d, years):
    """Advance a calendar date by whole years keeping month and day."""
    try:
        return d.replace(year=d.year + years)
    except ValueError:  # 29 February in a non-leap target year
        return d.replace(year=d.year + years, day=28)


# --------------------------------------------------------------------------
# decimal helpers -- every rounding operation rounds half away from zero
# --------------------------------------------------------------------------
D0 = Decimal("0")
D2 = Decimal("0.01")
D4 = Decimal("0.0001")


def dec(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def q2(value):
    return dec(value).quantize(D2, rounding=ROUND_HALF_UP)


def q4(value):
    return dec(value).quantize(D4, rounding=ROUND_HALF_UP)


ZERO2 = q2(0)
ONE4 = q4(1)


# --------------------------------------------------------------------------
# row bookkeeping
# --------------------------------------------------------------------------
def new_row(kind, versioned=True, **fields):
    row = {"id": db.new_id()}
    row.update(fields)
    row["created_at"] = now_iso()
    if versioned:
        row["updated_at"] = now_iso()
        row["version"] = 1
    row["_kind"] = kind
    row["_seq"] = db.next_seq()
    return row


def touch(row, touched):
    """Bump version/updated_at at most once per request for a given row."""
    if row is None:
        return
    key = row.get("id")
    if key in touched:
        return
    touched.add(key)
    if "version" in row:
        row["version"] = row["version"] + 1
    if "updated_at" in row:
        row["updated_at"] = now_iso()


def public(row):
    return {k: v for k, v in row.items() if not k.startswith("_")}


def order_key(row):
    return (row.get("created_at") or "", row.get("_seq") or 0)


def sorted_rows(rows):
    return sorted(rows, key=order_key)


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))
