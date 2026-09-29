"""In-memory storage, the logical UTC clock and shared primitives.

Storage is plain Python dicts held in this module's singleton ``Store``.
Nothing is persisted and nothing is seeded: a fresh process starts completely
empty with the logical clock reading exactly 2026-08-01T00:00:00Z (PRD 2.4).
"""

import datetime
import random
import re
import string
import uuid
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

UTC = datetime.timezone.utc

DEFAULT_CLOCK_RAW = "2026-08-01T00:00:00Z"
DEFAULT_CLOCK_DT = datetime.datetime(2026, 8, 1, 0, 0, 0, tzinfo=UTC)

_ISO_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2}):(\d{2})(\.\d{1,9})?"
    r"(Z|z|[+-]\d{2}:\d{2})?$"
)


class Store(object):
    """Every collection in the API. Recreated once per process."""

    def __init__(self):
        self.markets = {}
        self.segments = {}
        self.programs = {}
        self.channels = {}
        self.policies = {}
        self.plans = {}
        self.allocations = {}
        self.vehicles = {}
        self.tasks = {}
        self.orders = {}
        self.damage_events = {}
        self.consignments = {}
        self.ledger = {}
        self.clock_dt = DEFAULT_CLOCK_DT
        self.clock_raw = DEFAULT_CLOCK_RAW
        self._seq = 0

    # -- identity / sequencing ------------------------------------------
    def next_seq(self):
        self._seq += 1
        return self._seq

    # -- clock ----------------------------------------------------------
    def now(self):
        return self.clock_dt

    def now_iso(self):
        return iso(self.clock_dt)

    def set_clock(self, dt, raw):
        self.clock_dt = dt
        self.clock_raw = raw


store = Store()


def new_id():
    return str(uuid.uuid4())


def request_id():
    alphabet = string.ascii_uppercase + string.digits
    return "req_" + "".join(random.choice(alphabet) for _ in range(20))


def iso(dt):
    """ISO-8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    dt = dt.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        dt.year, dt.month, dt.day, dt.hour, dt.minute, dt.second,
        dt.microsecond // 1000,
    )


def parse_instant(value):
    """Parse an ISO-8601 UTC instant. Returns None when unparseable."""
    if not isinstance(value, str):
        return None
    m = _ISO_RE.match(value.strip())
    if not m:
        return None
    year, month, day, hour, minute, second = (int(m.group(i)) for i in range(1, 7))
    frac = m.group(7)
    micro = 0
    if frac:
        digits = (frac[1:] + "000000")[:6]
        micro = int(digits)
    offset = m.group(8)
    try:
        dt = datetime.datetime(year, month, day, hour, minute, second, micro, tzinfo=UTC)
    except ValueError:
        return None
    if offset and offset not in ("Z", "z"):
        sign = 1 if offset[0] == "+" else -1
        oh = int(offset[1:3])
        om = int(offset[4:6])
        dt = dt - sign * datetime.timedelta(hours=oh, minutes=om)
    return dt


# -- arithmetic --------------------------------------------------------


def dec(value):
    """Decimal from int / float / str without binary float noise."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def round_half_up(value):
    """Round to the nearest whole cent, halves away from zero."""
    return int(dec(value).quantize(Decimal(1), rounding=ROUND_HALF_UP))


def round_half_up_4(value):
    """Round to four decimal places, halves away from zero."""
    return dec(value).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)


def floor_div(numerator, denominator):
    """Integer floor of a division (truncation toward negative infinity)."""
    if denominator == 0:
        return 0
    return int((dec(numerator) / dec(denominator)).to_integral_value(rounding=ROUND_FLOOR))


# -- row helpers -------------------------------------------------------


def base_row(versioned=True):
    now = store.now_iso()
    row = {
        "id": new_id(),
        "created_at": now,
        "_seq": store.next_seq(),
    }
    if versioned:
        row["updated_at"] = now
        row["version"] = 1
    return row


def touch(row, bump=True):
    """Refresh updated_at and (by default) increment version by one."""
    row["updated_at"] = store.now_iso()
    if bump:
        row["version"] = row.get("version", 1) + 1
    return row


def sort_rows(rows, keys=("created_at",)):
    def key(row):
        return tuple(row.get(k) or "" for k in keys) + (row.get("_seq", 0),)

    return sorted(rows, key=key)
