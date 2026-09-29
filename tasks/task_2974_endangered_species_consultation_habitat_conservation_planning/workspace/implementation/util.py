"""Low-level helpers: decimal rounding, ISO-8601 formats, JSON serialisation.

Every rounding step in this API is HALF UP with ties away from zero
(PRD 2.8).  Banker's rounding is never used anywhere.
"""
import datetime
import json
import random
import re
import string
import uuid
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

UTC = datetime.timezone.utc

ZERO = Decimal("0")

# ---------------------------------------------------------------- decimals --

_Q = {
    0: Decimal("1"),
    2: Decimal("0.01"),
    3: Decimal("0.001"),
    4: Decimal("0.0001"),
}


def to_dec(value):
    """Coerce int / Decimal / str / float into a Decimal."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):
        return Decimal(int(value))
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places=0):
    """round_half_up(value, places) -> Decimal with exactly `places` digits."""
    quant = _Q.get(places)
    if quant is None:
        quant = Decimal(1).scaleb(-places)
    return to_dec(value).quantize(quant, rounding=ROUND_HALF_UP)


def rhu_int(value):
    """round_half_up to whole units, returned as a Python int (money)."""
    return int(rhu(value, 0))


def q2(value):
    return rhu(value, 2)


def q3(value):
    return rhu(value, 3)


def q4(value):
    return rhu(value, 4)


def decimal_places(value):
    """Number of fractional digits carried by a JSON-parsed number."""
    d = to_dec(value)
    exp = d.as_tuple().exponent
    if not isinstance(exp, int):
        return 99
    return max(0, -exp)


# -------------------------------------------------------------- timestamps --

INSTANT_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(\.\d{3})?Z$")
DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


def parse_instant(text):
    """ISO-8601 UTC with trailing Z, whole seconds or exactly 3 fractional
    digits.  Returns an aware datetime, or None when malformed."""
    if not isinstance(text, str):
        return None
    m = INSTANT_RE.match(text)
    if not m:
        return None
    frac = m.group(7)
    micros = int(frac[1:]) * 1000 if frac else 0
    try:
        return datetime.datetime(
            int(m.group(1)), int(m.group(2)), int(m.group(3)),
            int(m.group(4)), int(m.group(5)), int(m.group(6)),
            micros, tzinfo=UTC,
        )
    except ValueError:
        return None


def fmt_instant(moment):
    """ISO-8601 UTC with exactly three fractional digits and a trailing Z."""
    if moment is None:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return "%04d-%02d-%02dT%02d:%02d:%02d.%03dZ" % (
        moment.year, moment.month, moment.day,
        moment.hour, moment.minute, moment.second,
        moment.microsecond // 1000,
    )


def parse_date(text):
    """Plain YYYY-MM-DD calendar date.  Returns a date, or None when malformed."""
    if not isinstance(text, str):
        return None
    m = DATE_RE.match(text)
    if not m:
        return None
    try:
        return datetime.date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def fmt_date(day):
    if day is None:
        return None
    return "%04d-%02d-%02d" % (day.year, day.month, day.day)


def date_of(moment):
    if moment is None:
        return None
    if moment.tzinfo is not None:
        moment = moment.astimezone(UTC)
    return moment.date()


def at_midnight(day):
    return datetime.datetime(day.year, day.month, day.day, tzinfo=UTC)


def whole_days_between(earlier, later):
    """floor((later - earlier) / 86400 seconds) -- partial days discarded."""
    delta = later - earlier
    return int(delta.total_seconds() // 86400)


def add_days(day, count):
    return day + datetime.timedelta(days=count)


def add_years_clamped(day, years):
    """Calendar-year addition keeping month/day; 02-29 clamps to 02-28 when the
    target year is not a leap year (PRD 3.8, normative)."""
    target_year = day.year + years
    try:
        return datetime.date(target_year, day.month, day.day)
    except ValueError:
        return datetime.date(target_year, 2, 28)


# ------------------------------------------------------------------- ids ----

_ALNUM = string.ascii_uppercase + string.digits


def new_uuid():
    """Server-minted id: a bare UUID with no type prefix of any kind."""
    return str(uuid.uuid4())


def new_request_id():
    return "req_" + "".join(random.choice(_ALNUM) for _ in range(20))


# ------------------------------------------------------------ json output ---
# Quantities must be emitted with their trailing zeros intact (0.00, 0.0000).
# json.dumps cannot do that for Decimal, so Decimals are serialised through a
# sentinel string that is unwrapped afterwards.

_MARK = "DEC"
_MARK_RE = re.compile(r'"DEC(-?\d+(?:\.\d+)?)DEC"')


def _json_default(obj):
    if isinstance(obj, Decimal):
        return _MARK + format(obj, "f") + _MARK
    if isinstance(obj, datetime.datetime):
        return fmt_instant(obj)
    if isinstance(obj, datetime.date):
        return fmt_date(obj)
    raise TypeError("not JSON serialisable")


def dumps(payload):
    text = json.dumps(payload, default=_json_default, ensure_ascii=False)
    return _MARK_RE.sub(lambda m: m.group(1), text)


def _reject_constant(name):
    raise ValueError("bare JSON constant is not accepted")


def loads_body(raw_bytes):
    """Parse a request body.  Non-integer numbers become Decimal so that the
    submitted number of decimal places stays observable.  Returns
    (parsed, ok); ok is False when the payload is not valid JSON."""
    if raw_bytes is None:
        return None, False
    if isinstance(raw_bytes, bytes):
        try:
            raw_bytes = raw_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return None, False
    if raw_bytes.strip() == "":
        return {}, True
    try:
        return json.loads(
            raw_bytes, parse_float=Decimal, parse_constant=_reject_constant
        ), True
    except (ValueError, InvalidOperation):
        return None, False
