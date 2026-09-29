"""In-memory store, id/timestamp helpers, logical clock, version bookkeeping.

Storage is plain Python dicts held in module state: every byte of state is lost
when the process exits, which is exactly the fresh-boot contract the harness
relies on.  Nothing is seeded here or anywhere else.
"""
import datetime as _dt
import itertools
import random
import string
import uuid
from decimal import Decimal, ROUND_HALF_UP

import config

UTC = _dt.timezone.utc

COLLECTIONS = (
    "districts",
    "businesses",
    "drives",
    "signatures",
    "periods",
    "statements",
    "remittances",
    "plans",
    "programs",
    "claims",
    "records",
    "disputes",
)


class _State(object):
    def __init__(self):
        self.reset()

    def reset(self):
        for name in COLLECTIONS:
            setattr(self, name, {})
        self.clock = parse_instant(config.DEFAULT_CLOCK)
        self._seq = itertools.count(1)
        self._touched = set()

    def next_seq(self):
        return next(self._seq)


# ---------------------------------------------------------------------------
# instants
# ---------------------------------------------------------------------------
def parse_instant(value):
    """Parse an ISO-8601 date or instant into an aware UTC datetime."""
    if not isinstance(value, str):
        raise ValueError("not a string")
    text = value.strip()
    if not text:
        raise ValueError("empty")
    if text.endswith(("Z", "z")):
        text = text[:-1] + "+00:00"
    try:
        parsed = _dt.datetime.fromisoformat(text)
    except ValueError:
        raise ValueError("unparseable instant: %r" % value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso3(moment):
    """ISO-8601 UTC with exactly three fractional digits (PRD 2.5)."""
    if moment is None:
        return None
    moment = moment.astimezone(UTC)
    return moment.strftime("%Y-%m-%dT%H:%M:%S.") + ("%03d" % (moment.microsecond // 1000)) + "Z"


def wall_now():
    return _dt.datetime.now(tz=UTC)


def add_days(moment, days):
    return moment + _dt.timedelta(days=days)


def add_years(moment, years):
    """Calendar-year addition, clamping 29 February onto 28 February."""
    year = moment.year + int(years)
    try:
        return moment.replace(year=year)
    except ValueError:
        return moment.replace(year=year, day=28)


def whole_days_between(start, end):
    """Whole days from start to end, floored; negative when end precedes start."""
    return int((end - start).total_seconds() // 86400)


# ---------------------------------------------------------------------------
# decimals
# ---------------------------------------------------------------------------
def rhu_cents(value):
    """Round half up to whole cents, returning an int."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def rhu4(value):
    """Round half up to four decimal places, returning a Decimal."""
    return Decimal(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def ratio_out(value):
    if value is None:
        return None
    return float(rhu4(value))


# ---------------------------------------------------------------------------
# identifiers
# ---------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


_ALPHANUM = string.ascii_uppercase + string.digits


def new_request_id():
    return "req_" + "".join(random.choice(_ALPHANUM) for _ in range(20))


# ---------------------------------------------------------------------------
# record bookkeeping
# ---------------------------------------------------------------------------
state = _State()


def begin_request():
    state._touched = set()


def new_record(kind, record_id=None):
    """Create the common-field skeleton (PRD 2.5).  version starts at 1."""
    stamp = wall_now()
    rec = {
        "id": record_id or new_id(),
        "created_at": stamp,
        "updated_at": stamp,
        "version": 1,
        "_kind": kind,
        "_seq": state.next_seq(),
        "_raw": {},
    }
    state._touched.add(id(rec))
    return rec


def touch(rec):
    """Bump version/updated_at at most once per record per request."""
    if id(rec) in state._touched:
        return False
    state._touched.add(id(rec))
    rec["version"] = rec["version"] + 1
    rec["updated_at"] = wall_now()
    return True


def set_if_changed(rec, updates):
    """Apply updates; touch the record only when a stored value really changes."""
    changed = False
    for key, value in updates.items():
        if rec.get(key) != value:
            rec[key] = value
            changed = True
    if changed:
        touch(rec)
    return changed


def put(collection, rec):
    getattr(state, collection)[rec["id"]] = rec
    return rec


def sorted_records(records):
    """Default ordering: created_at ascending, insertion order as tie-break."""
    return sorted(records, key=lambda r: (r["created_at"], r["_seq"]))


def clock():
    return state.clock
