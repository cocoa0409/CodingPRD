"""Core constants, the logical clock, id minting and envelope helpers.

Nothing in this module is seeded into the store: the store begins empty and
every entity is created through the API surface.
"""
import random
import string
import threading
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP

# --- logical clock -----------------------------------------------------------
DEFAULT_CLOCK = "2026-09-01T00:00:00Z"
# A fixed offset added to the logical clock so that server-generated
# created_at / updated_at insets differ between two resources minted inside one
# request (the standings and the pool ranking key on created_at).
STAMP_STRIDE_MS = 1

_lock = threading.RLock()
_now = datetime(2026, 9, 1, 0, 0, 0, 0, tzinfo=timezone.utc)
_stamp = [_now]


def now():
    """The logical clock's current reading (microsecond resolution)."""
    with _lock:
        return _now


def set_clock(iso):
    """Pin the logical clock to ``iso``; raise ValueError when unparseable.

    A naive instant is read as UTC: the default instant is spelled
    ``2026-09-01T00:00:00Z`` and callers routinely supply a bare local style.
    """
    global _now
    dt = parse_dt(iso, strict=True)
    with _lock:
        _now = dt
        _stamp[0] = dt
    return dt


def stamp(within=30.0):
    """A creation/update instant, distinct per call within one request.

    Retail tests never compare the wall value, but ordering a projection needs
    two resources made by one operation to be distinguishable.
    """
    with _lock:
        base = _now
        s = _stamp[0]
        if s < base or (s - base).total_seconds() > within:
            s = base
        _stamp[0] = s + _timedelta_ms(STAMP_STRIDE_MS)
        return s


def _timedelta_ms(ms):
    from datetime import timedelta
    return timedelta(milliseconds=ms)


def iso(dt):
    """ISO 8601 UTC with exactly three fractional digits."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def envelope_ts(dt=None):
    return iso(dt if dt is not None else now())


_DT_FORMATS = (
    "%Y-%m-%dT%H:%M:%S.%f%z",
    "%Y-%m-%dT%H:%M:%S%z",
    "%Y-%m-%dT%H:%M:%S.%f",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y-%m-%d",
)


def parse_dt(value, strict=False):
    """Parse an ISO 8601 instant; naive instants are read as UTC."""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        text = value.strip()
        if text.endswith("Z") or text.endswith("z"):
            text = text[:-1] + "+0000"
        dt = None
        for fmt in _DT_FORMATS:
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        if dt is None:
            if strict:
                raise ValueError("unparseable instant: %s" % value)
            return None
    elif isinstance(value, (int, float)):
        dt = datetime.fromtimestamp(value, tz=timezone.utc)
    else:
        if strict:
            raise ValueError("unparseable instant: %r" % (value,))
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def is_instant(value):
    if not isinstance(value, str):
        return False
    return parse_dt(value) is not None


def add_days(dt, days):
    from datetime import timedelta
    return dt + timedelta(days=days)


# --- money / basis points ----------------------------------------------------
CENT = Decimal("1")


def d(value):
    """Coerce an input to Decimal exactly (never through a float)."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, float):
        return Decimal(repr(value))
    return Decimal(str(value))


def r2c(value):
    """Round half up to a whole cent, returning an int."""
    return int(d(value).quantize(CENT, rounding=ROUND_HALF_UP))


def round2(value):
    """Round half up to two decimals, returning a Decimal."""
    return d(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def floor_div(numerator, denominator):
    """Integer division truncating toward zero (the pinned ratio behaviour)."""
    n = d(numerator)
    den = d(denominator)
    if den == 0:
        return 0
    return int(n / den)


def floor_minutes(seconds):
    return int(d(seconds) // 1 if int(seconds) == d(seconds) else int(d(seconds)))


def clamp(value, low, high):
    if low is not None and value < low:
        return low
    if high is not None and value > high:
        return high
    return value


# --- ids ---------------------------------------------------------------------
_ALPHANUM = string.ascii_uppercase + string.digits


def new_id():
    """A bare UUID-shaped identifier carrying no readable type mnemonic."""
    h = "0123456789abcdef"
    parts = [
        "".join(random.choice(h) for _ in range(8)),
        "".join(random.choice(h) for _ in range(4)),
        "4" + "".join(random.choice(h) for _ in range(3)),
        random.choice("89ab") + "".join(random.choice(h) for _ in range(3)),
        "".join(random.choice(h) for _ in range(12)),
    ]
    return "-".join(parts)


def new_request_id():
    body = "".join(random.choice(_ALPHANUM) for _ in range(18))
    return "req_" + body


LAST_OPS = {}


def note_op(path, status, code=None):
    with _lock:
        LAST_OPS["path"] = path
        LAST_OPS["status"] = status
        LAST_OPS["code"] = code