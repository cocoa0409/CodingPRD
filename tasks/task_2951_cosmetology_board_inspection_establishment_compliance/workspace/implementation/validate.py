"""Request-shape validation and parsing helpers (PRD 2.9 step 7)."""
import re
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation

from errors import fail

BAD = "ERR_INVALID_REQUEST"

_INSTANT_RE = re.compile(
    r"^(\d{4})-(\d{2})-(\d{2})[Tt ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,9}))?)?"
    r"(Z|z|[+-]\d{2}:?\d{2})?$"
)
_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")


# ----------------------------------------------------------------- numerics
def d2(value):
    """Quantize to two decimal places, rounding half up."""
    return Decimal(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def cents(value):
    """Quantize to whole cents, rounding half up."""
    return int(Decimal(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def f2(value):
    """Render a 2dp decimal as a JSON number."""
    if value is None:
        return None
    return float(d2(value))


# ---------------------------------------------------------------- instants
def parse_instant(raw, field):
    """Parse an ISO-8601 UTC instant.  A time component is required."""
    if not isinstance(raw, str):
        fail(BAD, "Field '%s' must be an ISO 8601 UTC instant." % field)
    m = _INSTANT_RE.match(raw.strip())
    if not m:
        fail(BAD, "Field '%s' must be an ISO 8601 UTC instant." % field)
    y, mo, d, hh, mi = (int(m.group(i)) for i in range(1, 6))
    ss = int(m.group(6) or 0)
    frac = m.group(7) or ""
    micro = int((frac + "000000")[:6]) if frac else 0
    tz = m.group(8)
    try:
        dt = datetime(y, mo, d, hh, mi, ss, micro, tzinfo=timezone.utc)
    except ValueError:
        fail(BAD, "Field '%s' must be an ISO 8601 UTC instant." % field)
    if tz and tz not in ("Z", "z"):
        sign = 1 if tz[0] == "+" else -1
        body = tz[1:].replace(":", "")
        offset = timedelta(hours=int(body[:2]), minutes=int(body[2:4]))
        dt = dt - sign * offset
    return dt


def parse_date(raw, field):
    if not isinstance(raw, str):
        fail(BAD, "Field '%s' must be an ISO 8601 calendar date." % field)
    m = _DATE_RE.match(raw.strip())
    if not m:
        fail(BAD, "Field '%s' must be an ISO 8601 calendar date." % field)
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        fail(BAD, "Field '%s' must be an ISO 8601 calendar date." % field)


def iso_date(d):
    return None if d is None else d.isoformat()


# ------------------------------------------------------------------- fields
_MISSING = object()


def body_of(request):
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        fail(BAD, "Request body must be a JSON object.")
    return payload


def present(body, name):
    return name in body and body[name] is not None


def req_str(body, name, max_len=None, allow_blank=False):
    if name not in body or body[name] is None:
        fail(BAD, "Field '%s' is required." % name)
    value = body[name]
    if not isinstance(value, str):
        fail(BAD, "Field '%s' must be a string." % name)
    if not allow_blank and value.strip() == "":
        fail(BAD, "Field '%s' must be non-empty." % name)
    if max_len is not None and len(value) > max_len:
        fail(BAD, "Field '%s' must be at most %d characters." % (name, max_len))
    return value


def opt_str(body, name, max_len=None):
    if name not in body or body[name] is None:
        return None
    value = body[name]
    if not isinstance(value, str):
        fail(BAD, "Field '%s' must be a string." % name)
    if max_len is not None and len(value) > max_len:
        fail(BAD, "Field '%s' must be at most %d characters." % (name, max_len))
    return value


def req_enum(body, name, members):
    value = req_str(body, name)
    if value not in members:
        fail(BAD, "Field '%s' must be one of %s." % (name, ", ".join(sorted(members))))
    return value


def opt_enum(body, name, members, default=None):
    if name not in body or body[name] is None:
        return default
    return req_enum(body, name, members)


def _as_int(value, name):
    if isinstance(value, bool) or not isinstance(value, int):
        fail(BAD, "Field '%s' must be an integer." % name)
    return value


def req_int(body, name, minimum=None, maximum=None):
    if name not in body or body[name] is None:
        fail(BAD, "Field '%s' is required." % name)
    value = _as_int(body[name], name)
    if minimum is not None and value < minimum:
        fail(BAD, "Field '%s' must be >= %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail(BAD, "Field '%s' must be <= %s." % (name, maximum))
    return value


def opt_int(body, name, minimum=None, maximum=None, default=None):
    if name not in body or body[name] is None:
        return default
    return req_int(body, name, minimum, maximum)


def _as_dec(value, name):
    if isinstance(value, bool):
        fail(BAD, "Field '%s' must be a number." % name)
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            fail(BAD, "Field '%s' must be a number." % name)
    fail(BAD, "Field '%s' must be a number." % name)


def req_dec(body, name, gt=None, ge=None, le=None):
    if name not in body or body[name] is None:
        fail(BAD, "Field '%s' is required." % name)
    value = _as_dec(body[name], name)
    if gt is not None and not value > Decimal(str(gt)):
        fail(BAD, "Field '%s' must be > %s." % (name, gt))
    if ge is not None and value < Decimal(str(ge)):
        fail(BAD, "Field '%s' must be >= %s." % (name, ge))
    if le is not None and value > Decimal(str(le)):
        fail(BAD, "Field '%s' must be <= %s." % (name, le))
    return value


def req_bool(body, name, default=_MISSING):
    if name not in body or body[name] is None:
        if default is _MISSING:
            fail(BAD, "Field '%s' is required." % name)
        return default
    value = body[name]
    if not isinstance(value, bool):
        fail(BAD, "Field '%s' must be a boolean." % name)
    return value


def req_instant(body, name):
    if name not in body or body[name] is None:
        fail(BAD, "Field '%s' is required." % name)
    return parse_instant(body[name], name)


def opt_instant(body, name, default=None):
    if name not in body or body[name] is None:
        return default
    return parse_instant(body[name], name)


def req_date(body, name):
    if name not in body or body[name] is None:
        fail(BAD, "Field '%s' is required." % name)
    return parse_date(body[name], name)


def county_code(body, name="county_code"):
    value = req_str(body, name)
    if not re.match(r"^[A-Z]{3}$", value):
        fail(BAD, "Field '%s' must be exactly three uppercase letters." % name)
    return value


def fk(body, name):
    """Return a body foreign key as a string, or None when absent/null."""
    if name not in body or body[name] is None:
        return None
    value = body[name]
    if not isinstance(value, str):
        return "\x00invalid"
    return value


# ---------------------------------------------------------------- pagination
def pagination(args):
    limit = 10
    offset = 0
    if "limit" in args:
        raw = args.get("limit")
        if raw is None or not re.match(r"^-?\d+$", str(raw).strip()):
            fail(BAD, "Query parameter 'limit' must be an integer.")
        limit = int(str(raw).strip())
        if limit < 1 or limit > 100:
            fail(BAD, "Query parameter 'limit' must be within [1, 100].")
    if "offset" in args:
        raw = args.get("offset")
        if raw is None or not re.match(r"^-?\d+$", str(raw).strip()):
            fail(BAD, "Query parameter 'offset' must be an integer.")
        offset = int(str(raw).strip())
        if offset < 0:
            fail(BAD, "Query parameter 'offset' must be >= 0.")
    return limit, offset


def qbool(args, name):
    if name not in args:
        return None
    raw = str(args.get(name)).strip().lower()
    if raw in ("true", "1", "yes"):
        return True
    if raw in ("false", "0", "no"):
        return False
    return "\x00invalid"
