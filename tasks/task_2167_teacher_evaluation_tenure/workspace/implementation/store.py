"""In-memory store, logical district clock and shared record helpers.

The store starts EMPTY on every boot.  Nothing is seeded, preloaded or
hardcoded; every entity is created by clients through the declared endpoints.
"""
import itertools
import uuid
from datetime import datetime, timezone, timedelta, date
from decimal import Decimal, ROUND_HALF_UP

# PRD 2.11 -- before any operator sets it the logical clock reads exactly this.
DEFAULT_CLOCK = datetime(2026, 8, 1, 0, 0, 0, tzinfo=timezone.utc)

ROLES = ("HrAdmin", "Evaluator", "Teacher", "AppealPanelist", "UnionRep")


class _State(object):
    def __init__(self):
        self.clock = DEFAULT_CLOCK
        self._seq = itertools.count(1)
        self.policies = {}
        self.schools = {}
        self.educators = {}
        self.evaluators = {}
        self.cycles = {}
        self.observations = {}
        self.rubric_scores = {}
        self.artifacts = {}
        self.growth_measures = {}
        self.plans = {}
        self.appeals = {}
        self.grievances = {}
        self.calibrations = {}

    def next_seq(self):
        return next(self._seq)


S = _State()


# ---------------------------------------------------------------- time helpers
def now():
    """The logical district clock."""
    return S.clock


def clock_date():
    return S.clock.astimezone(timezone.utc).date()


def fmt_dt(dt):
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def fmt_date(d):
    if d is None:
        return None
    return d.strftime("%Y-%m-%d")


def parse_dt(value):
    """Parse an ISO 8601 instant.  Returns an aware UTC datetime or None."""
    if not isinstance(value, str) or not value.strip():
        return None
    txt = value.strip()
    if txt.endswith("Z") or txt.endswith("z"):
        txt = txt[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(txt)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_date(value):
    if not isinstance(value, str):
        return None
    txt = value.strip()
    try:
        return datetime.strptime(txt, "%Y-%m-%d").date()
    except ValueError:
        return None


def real_now_iso():
    dt = datetime.now(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


# ------------------------------------------------------------- record helpers
def new_record(**fields):
    stamp = fmt_dt(S.clock)
    rec = {
        "id": str(uuid.uuid4()),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
    }
    rec["_seq"] = S.next_seq()
    rec.update(fields)
    return rec


def touch(rec):
    """Every mutation refreshes updated_at and bumps version by exactly 1."""
    rec["updated_at"] = fmt_dt(S.clock)
    rec["version"] = rec["version"] + 1
    return rec


def order_key(rec):
    return (rec["created_at"], rec["_seq"])


def sorted_records(records):
    return sorted(records, key=order_key)


# ------------------------------------------------------------ decimal helpers
def D(value):
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value, places):
    exp = Decimal(1).scaleb(-places) if places > 0 else Decimal(1)
    return D(value).quantize(exp, rounding=ROUND_HALF_UP)


def num(value):
    """JSON-friendly rendering of a Decimal."""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return value


def add_days(dt, days):
    return dt + timedelta(days=int(days))
