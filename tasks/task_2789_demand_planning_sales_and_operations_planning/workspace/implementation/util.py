"""Logical clock, id generation, calendar helpers and rounding discipline."""
import random
import re
import string
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING, ROUND_FLOOR, getcontext

getcontext().prec = 60

MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
INT_RE = re.compile(r"^-?\d+$")


def fmt_instant(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


class LogicalClock(object):
    """Never falls back to wall-clock time."""

    def __init__(self):
        self.dt = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

    def now(self):
        return self.dt

    def now_iso(self):
        return fmt_instant(self.dt)

    def now_month(self):
        return "%04d-%02d" % (self.dt.year, self.dt.month)

    def set_from_iso(self, raw):
        self.dt = parse_iso8601(raw)
        return self.now_iso()


clock = LogicalClock()


def parse_iso8601(raw):
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError("bad instant")
    txt = raw.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    dt = datetime.fromisoformat(txt)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def new_id():
    return str(uuid.uuid4())


def new_request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


# --------------------------------------------------------------------------
# rounding discipline (2.6): round half up, ceiling, floor
# --------------------------------------------------------------------------
def D(x):
    if isinstance(x, Decimal):
        return x
    if isinstance(x, bool):
        return Decimal(int(x))
    if isinstance(x, int):
        return Decimal(x)
    return Decimal(str(x))


def round_half_up(x, dp=0):
    quant = Decimal(1).scaleb(-dp)
    return D(x).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(x):
    return int(round_half_up(x, 0))


def rhu2(x):
    """Two decimal places, returned as a JSON number."""
    return float(round_half_up(x, 2))


def ceil_int(x):
    return int(D(x).to_integral_value(rounding=ROUND_CEILING))


def floor_int(x):
    return int(D(x).to_integral_value(rounding=ROUND_FLOOR))


def dsqrt(x):
    return D(x).sqrt()


# --------------------------------------------------------------------------
# calendar helpers -- month strings compare lexicographically
# --------------------------------------------------------------------------
def is_month(v):
    return isinstance(v, str) and bool(MONTH_RE.match(v))


def is_date(v):
    if not isinstance(v, str) or not DATE_RE.match(v):
        return False
    try:
        date(int(v[0:4]), int(v[5:7]), int(v[8:10]))
    except ValueError:
        return False
    return True


def month_index(m):
    return int(m[0:4]) * 12 + (int(m[5:7]) - 1)


def month_offset(month, start_month):
    return month_index(month) - month_index(start_month)


def add_months(m, n):
    idx = month_index(m) + n
    return "%04d-%02d" % (idx // 12, (idx % 12) + 1)


def first_day(m):
    return m + "-01"


def parse_date(v):
    return date(int(v[0:4]), int(v[5:7]), int(v[8:10]))


def shift_date(v, days):
    return (parse_date(v) + timedelta(days=days)).isoformat()


def month_of_date(v):
    return v[0:7]
