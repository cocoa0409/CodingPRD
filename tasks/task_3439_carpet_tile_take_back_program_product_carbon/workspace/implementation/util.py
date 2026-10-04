"""Shared parsing, rounding and request-shape helpers.

All rounding in the system is round-half-up at the stated number of decimal
places (PRD 2.6); no other rounding mode is permitted anywhere. Shape failures
raise ERR_INVALID_REQUEST (HTTP 400) — the validation pipeline evaluates
request shape at priority 11, so route handlers invoke these helpers only at
that stage, after existence/state/OCC/SoD/referential/temporal checks.
"""
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from errors import ApiError

CENT = Decimal("0.01")
MILLI = Decimal("0.001")
TENTH_MILLI = Decimal("0.0001")


def q2(d):
    return d.quantize(CENT, rounding=ROUND_HALF_UP)


def q3(d):
    return d.quantize(MILLI, rounding=ROUND_HALF_UP)


def q4(d):
    return d.quantize(TENTH_MILLI, rounding=ROUND_HALF_UP)


def q0(d):
    return d.quantize(Decimal("1"), rounding=ROUND_HALF_UP)


def parse_dt(value):
    """Parse an ISO-8601 timestamp into an aware UTC datetime; None if invalid."""
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_dt(dt):
    """ISO 8601 UTC with three fractional digits (PRD 2.2/2.4)."""
    if dt is None:
        return None
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (dt.microsecond // 1000)


def is_int(value):
    return isinstance(value, int) and not isinstance(value, bool)


def to_decimal(value):
    """Coerce a JSON scalar to Decimal without float noise; None if not numeric."""
    if isinstance(value, bool):
        return None
    if isinstance(value, Decimal):
        return value if value.is_finite() else None
    if isinstance(value, (int, float, str)):
        try:
            d = Decimal(str(value))
        except InvalidOperation:
            return None
        return d if d.is_finite() else None
    return None


def _bad(field, msg):
    raise ApiError("ERR_INVALID_REQUEST", 400, "Field '%s': %s" % (field, msg))


def get_body():
    from flask import request

    body = request.get_json(silent=True)
    if not isinstance(body, dict):
        return {}
    return body


def req_str(body, field):
    v = body.get(field)
    if not isinstance(v, str):
        _bad(field, "required string")
    return v


def opt_str(body, field):
    v = body.get(field)
    if v is None:
        return None
    if not isinstance(v, str):
        _bad(field, "must be a string")
    return v


def req_enum(body, field, allowed):
    v = body.get(field)
    if not isinstance(v, str) or v not in allowed:
        _bad(field, "must be one of %s" % (", ".join(allowed)))
    return v


def opt_enum(body, field, allowed, default):
    v = body.get(field)
    if v is None:
        return default
    if not isinstance(v, str) or v not in allowed:
        _bad(field, "must be one of %s" % (", ".join(allowed)))
    return v


def req_decimal(body, field, min_exclusive=None, min_inclusive=None):
    v = to_decimal(body.get(field))
    if v is None:
        _bad(field, "required number")
    if min_exclusive is not None and not (v > min_exclusive):
        _bad(field, "must be > %s" % (min_exclusive,))
    if min_inclusive is not None and not (v >= min_inclusive):
        _bad(field, "must be >= %s" % (min_inclusive,))
    return v


def req_int(body, field, min_inclusive=None):
    raw = body.get(field)
    v = None
    if is_int(raw):
        v = raw
    elif isinstance(raw, float) and raw.is_integer():
        v = int(raw)
    if v is None:
        _bad(field, "required integer")
    if min_inclusive is not None and v < min_inclusive:
        _bad(field, "must be >= %d" % (min_inclusive,))
    return v


def req_bool(body, field):
    v = body.get(field)
    if not isinstance(v, bool):
        _bad(field, "required boolean")
    return v


def req_dt(body, field):
    dt = parse_dt(body.get(field))
    if dt is None:
        _bad(field, "required ISO-8601 timestamp")
    return dt


def pagination_params(args):
    """limit: default 10, min 1, max 100; offset: default 0, min 0 (PRD 2.3)."""
    limit = 10
    offset = 0
    raw_limit = args.get("limit")
    if raw_limit is not None:
        try:
            limit = int(raw_limit, 10)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be an integer")
        if limit < 1 or limit > 100:
            raise ApiError("ERR_INVALID_REQUEST", 400, "limit must be between 1 and 100")
    raw_offset = args.get("offset")
    if raw_offset is not None:
        try:
            offset = int(raw_offset, 10)
        except (ValueError, TypeError):
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_REQUEST", 400, "offset must be >= 0")
    return limit, offset


def created_key(ent):
    """created_at ascending; creation sequence breaks exact-timestamp ties."""
    return (ent["created_at"], ent["_seq"])
