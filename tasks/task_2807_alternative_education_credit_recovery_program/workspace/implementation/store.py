"""In-memory data store, logical clock and numeric helpers.

Storage is process-memory only: plain dicts keyed by uuid.  Nothing is
persisted and nothing is seeded -- every row is created through the API.
"""
import itertools
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

CLOCK_DEFAULT = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)


def fmt_ts(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def fmt_date(dt):
    dt = dt.astimezone(timezone.utc)
    return "%04d-%02d-%02d" % (dt.year, dt.month, dt.day)


class Store(object):
    def __init__(self):
        self.reset()

    def reset(self):
        self.home_schools = {}
        self.centers = {}
        self.students = {}
        self.courses = {}
        self.prior_records = {}
        self.referrals = {}
        self.placements = {}
        self.enrollments = {}
        self.awards = {}
        self.plans = {}
        self.stations = {}
        self.proctor_sessions = {}
        self.providers = {}
        self.support_sessions = {}
        self.clock = CLOCK_DEFAULT
        self._seq = itertools.count(1)
        self._last_ts = None

    # ---- logical clock -------------------------------------------------
    def clock_date(self):
        return fmt_date(self.clock)

    def clock_date_obj(self):
        return self.clock.astimezone(timezone.utc).date()

    # ---- system timestamps --------------------------------------------
    def stamp(self):
        """Strictly increasing wall-clock UTC timestamp.

        created_at / updated_at are row bookkeeping (the logical clock of
        PRD 2.4 stamps enrolled_on, posted_on and offer_expires_on).  The
        monotonic bump keeps `created_at ASC` orderings total.
        """
        s = fmt_ts(datetime.now(timezone.utc))
        if self._last_ts is not None and s <= self._last_ts:
            prev = datetime.strptime(self._last_ts, "%Y-%m-%dT%H:%M:%S.%fZ").replace(
                tzinfo=timezone.utc)
            s = fmt_ts(prev + timedelta(milliseconds=1))
        self._last_ts = s
        return s

    def next_seq(self):
        return next(self._seq)


store = Store()


def new_row(**fields):
    ts = store.stamp()
    row = dict(fields)
    row["id"] = str(uuid.uuid4())
    row["created_at"] = ts
    row["updated_at"] = ts
    row["version"] = 1
    row["_seq"] = store.next_seq()
    return row


def touch(row):
    row["updated_at"] = store.stamp()
    row["version"] = row["version"] + 1
    return row


def ordered(rows):
    """Default list ordering: created_at ascending (insertion order tie-break)."""
    return sorted(rows, key=lambda r: (r["created_at"], r["_seq"]))


# ---- numeric helpers --------------------------------------------------
def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def rnd(value, places):
    """round half up to `places` decimals; returns Decimal."""
    if value is None:
        return None
    q = Decimal(1).scaleb(-places)
    return D(value).quantize(q, rounding=ROUND_HALF_UP)


def floor_int(value):
    return int(D(value).to_integral_value(rounding=ROUND_FLOOR))


def floor_quarter(value):
    """Floor down to a multiple of 0.25 (PRD 2.5 credit granularity)."""
    steps = (D(value) * 4).to_integral_value(rounding=ROUND_FLOOR)
    return (steps / Decimal(4)).quantize(Decimal("0.01"))


def num(value):
    """Serialize a Decimal/None into a JSON number."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def dmin(a, b):
    return a if D(a) <= D(b) else b


def dmax(a, b):
    return a if D(a) >= D(b) else b
