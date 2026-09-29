"""In-memory store, logical clock and row bookkeeping helpers.

The store is always empty on boot: no seeding, no preloading, no persistence.
"""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP

from flask import g

from errors import fail

DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.clock = DEFAULT_CLOCK
        self._seq = 0
        self.children = {}
        self.coordinators = {}
        self.referrals = {}
        self.assessments = {}
        self.ifsps = {}
        self.ifsp_services = {}
        self.providers = {}
        self.authorizations = {}
        self.visits = {}
        self.cost_shares = {}
        self.contact_logs = {}
        self.transition_plans = {}

    def next_seq(self):
        self._seq += 1
        return self._seq


db = Store()


# ---------------------------------------------------------------- time helpers

def now():
    return db.clock


def clock_date():
    return db.clock.date()


def iso_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits and a trailing Z."""
    if dt is None:
        return None
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def now_iso():
    return iso_instant(db.clock)


_DT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2}))?(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)


def parse_instant(value):
    """Parse an ISO 8601 instant; returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    m = _DT_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute = (int(m.group(i)) for i in range(1, 6))
    second = int(m.group(6) or 0)
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    tz = m.group(8)
    try:
        naive = datetime(year, month, day, hour, minute, second, micro)
    except ValueError:
        return None
    if tz in (None, "Z", "z"):
        return naive.replace(tzinfo=timezone.utc)
    sign = 1 if tz[0] == "+" else -1
    body = tz[1:].replace(":", "")
    offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
    return (naive - sign * offset).replace(tzinfo=timezone.utc)


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


def pd(value):
    """Parse a stored date string (already validated) into a date."""
    return parse_date(value) if value else None


_MONTH_RE = re.compile(r"^(\d{4})-(\d{2})$")


def parse_month(value):
    if not isinstance(value, str):
        return None
    m = _MONTH_RE.match(value.strip())
    if not m:
        return None
    month = int(m.group(2))
    if month < 1 or month > 12:
        return None
    return value.strip()


def month_of(value):
    """The YYYY-MM bucket of a date string or an ISO instant string."""
    if not value:
        return None
    return value[:7]


def day_count(earlier, later):
    """Whole days between two dates, earlier exclusive and later inclusive."""
    if earlier is None or later is None:
        return None
    return (later - earlier).days


def add_years(d, years):
    try:
        return d.replace(year=d.year + years)
    except ValueError:
        # 29 February in a non-leap target year collapses to 28 February.
        return d.replace(year=d.year + years, month=2, day=28)


def iso_date(d):
    return None if d is None else d.isoformat()


# --------------------------------------------------------------- number helpers

def q(value, places):
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)


def q1(value):
    return float(q(value, 1))


def q2(value):
    return float(q(value, 2))


def q4(value):
    return float(q(value, 4))


def round_half_up_int(value):
    return int(Decimal(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def dec(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


# ------------------------------------------------------------------ row helpers

_ALNUM = string.ascii_uppercase + string.digits


def request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


def new_id():
    return str(uuid.uuid4())


def new_row(fields, versioned=True):
    stamp = now_iso()
    row = {"id": new_id(), "created_at": stamp}
    if versioned:
        row["updated_at"] = stamp
        row["version"] = 1
    row.update(fields)
    row["_seq"] = db.next_seq()
    created = getattr(g, "created_rows", None)
    if created is None:
        created = set()
        g.created_rows = created
    created.add(id(row))
    return row


def mark(row, bump=True):
    """Record that a row was touched by this request."""
    if row is None:
        return
    if "version" not in row:
        return
    created = getattr(g, "created_rows", None) or set()
    if id(row) in created:
        return
    touched = getattr(g, "touched_rows", None)
    if touched is None:
        touched = {}
        g.touched_rows = touched
    # PRD 2.2 and 2.7: every mutation of a row -- including one that arrives
    # as the secondary effect of a write aimed at a different resource --
    # refreshes updated_at and increments that row's version by exactly 1.
    # A row touched several times in one request is still versioned once.
    if id(row) not in touched:
        touched[id(row)] = [row, True]


def set_field(row, key, value, bump=True):
    if row.get(key) != value:
        row[key] = value
        mark(row, bump=bump)
        return True
    return False


def set_fields(row, values, bump=True):
    changed = False
    for key, value in values.items():
        if set_field(row, key, value, bump=bump):
            changed = True
    return changed


def flush():
    """Apply updated_at / version bookkeeping once per touched row."""
    touched = getattr(g, "touched_rows", None) or {}
    stamp = now_iso()
    for row, bump in touched.values():
        if bump:
            row["version"] = row.get("version", 1) + 1
        row["updated_at"] = stamp
    g.touched_rows = {}


def ordered(collection, values=None):
    rows = list(collection.values()) if values is None else list(values)
    rows.sort(key=lambda r: (r["created_at"], r["_seq"]))
    return rows


def public(row, fields):
    return {name: row.get(name) for name in fields}
