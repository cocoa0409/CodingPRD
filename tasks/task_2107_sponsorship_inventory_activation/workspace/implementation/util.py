"""Shared primitives: identity, the logical clock format, rounding discipline
(PRD 2.6) and request-shape validators (PRD 2.8 rung 5)."""

import random
import string
import uuid
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP, ROUND_FLOOR

from errors import ApiError

ALNUM = string.ascii_uppercase + string.digits


# --------------------------------------------------------------------------
# identity / timestamps
# --------------------------------------------------------------------------
def new_id():
    return str(uuid.uuid4())


def request_id():
    return "req_" + "".join(random.choice(ALNUM) for _ in range(20))


def fmt_iso(dt):
    """ISO 8601 UTC with exactly three fractional digits (PRD 2.4)."""
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def wall_now():
    return datetime.now(timezone.utc)


def wall_now_iso():
    return fmt_iso(wall_now())


def parse_dt(value):
    """Parse an ISO 8601 instant; returns an aware UTC datetime or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text[-1] in ("Z", "z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


# --------------------------------------------------------------------------
# rounding discipline (PRD 2.6)
# --------------------------------------------------------------------------
def dec(x):
    if isinstance(x, Decimal):
        return x
    return Decimal(str(x))


def rhu(x, places=0):
    """Round half up to `places` decimal places."""
    return dec(x).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def rhu_int(x):
    return int(rhu(x, 0))


def floor_int(x):
    return int(dec(x).to_integral_value(rounding=ROUND_FLOOR))


def num2(x):
    """A percentage / index style number carried at 2 decimal places."""
    return float(rhu(x, 2))


def num4(x):
    return float(rhu(x, 4))


def minutes_between(a, b):
    """Whole minutes from a to b (b - a)."""
    return int((b - a).total_seconds() // 60)


def gap_minutes(a, b):
    """Exact minute distance between two instants (b - a), may be fractional."""
    return dec((b - a).total_seconds()) / dec(60)


# --------------------------------------------------------------------------
# validators — every failure is ERR_VALIDATION_FAILED (422)
# --------------------------------------------------------------------------
_MISSING = object()


def fail(msg):
    raise ApiError("ERR_VALIDATION_FAILED", 422, msg)


def body_of(request):
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        fail("Request body must be a JSON object.")
    return data


def _present(body, key, required, default):
    if key not in body or body[key] is None:
        if required:
            fail("Field '%s' is required." % key)
        return False, default
    return True, body[key]


def v_str(body, key, required=True, default=None, min_len=None, max_len=None):
    present, value = _present(body, key, required, default)
    if not present:
        return value
    if not isinstance(value, str):
        fail("Field '%s' must be a string." % key)
    if min_len is not None and len(value) < min_len:
        fail("Field '%s' must be at least %d characters." % (key, min_len))
    if max_len is not None and len(value) > max_len:
        fail("Field '%s' must be at most %d characters." % (key, max_len))
    return value


def v_int(body, key, required=True, default=None, min_v=None, max_v=None):
    present, value = _present(body, key, required, default)
    if not present:
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        fail("Field '%s' must be an integer." % key)
    if min_v is not None and value < min_v:
        fail("Field '%s' must be >= %s." % (key, min_v))
    if max_v is not None and value > max_v:
        fail("Field '%s' must be <= %s." % (key, max_v))
    return value


def v_num(body, key, required=True, default=None, min_v=None, max_v=None, max_dp=None):
    present, value = _present(body, key, required, default)
    if not present:
        return dec(value) if value is not None else None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("Field '%s' must be a number." % key)
    d = dec(value)
    if max_dp is not None:
        exponent = d.normalize().as_tuple().exponent
        if isinstance(exponent, int) and exponent < -max_dp:
            fail("Field '%s' must carry at most %d decimal places." % (key, max_dp))
    if min_v is not None and d < dec(min_v):
        fail("Field '%s' must be >= %s." % (key, min_v))
    if max_v is not None and d > dec(max_v):
        fail("Field '%s' must be <= %s." % (key, max_v))
    return d


def v_bool(body, key, required=False, default=None):
    present, value = _present(body, key, required, default)
    if not present:
        return value
    if not isinstance(value, bool):
        fail("Field '%s' must be a boolean." % key)
    return value


def v_enum(body, key, allowed, required=True, default=None):
    present, value = _present(body, key, required, default)
    if not present:
        return value
    if not isinstance(value, str) or value not in allowed:
        fail("Field '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return value


def v_dt(body, key, required=True, default=None):
    """Returns (raw_string, datetime) so the raw client form can be echoed back."""
    present, value = _present(body, key, required, default)
    if not present:
        return None, None
    if not isinstance(value, str):
        fail("Field '%s' must be an ISO 8601 datetime string." % key)
    parsed = parse_dt(value)
    if parsed is None:
        fail("Field '%s' must be an ISO 8601 datetime string." % key)
    return value, parsed


def v_query_enum(request, key, allowed):
    raw = request.args.get(key)
    if raw is None:
        return None
    if raw not in allowed:
        fail("Query parameter '%s' must be one of %s." % (key, ", ".join(sorted(allowed))))
    return raw


def v_pagination(request):
    """limit defaults to 10 (1..100); offset defaults to 0 (>= 0). PRD 2.3."""
    limit = 10
    offset = 0
    raw_limit = request.args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(str(raw_limit).strip())
        except (TypeError, ValueError):
            fail("Query parameter 'limit' must be an integer.")
        if limit < 1 or limit > 100:
            fail("Query parameter 'limit' must be between 1 and 100.")
    raw_offset = request.args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(str(raw_offset).strip())
        except (TypeError, ValueError):
            fail("Query parameter 'offset' must be an integer.")
        if offset < 0:
            fail("Query parameter 'offset' must be zero or greater.")
    return limit, offset
