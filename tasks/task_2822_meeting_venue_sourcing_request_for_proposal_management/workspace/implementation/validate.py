"""Request-shape validation (PRD section 2.8 band 6) and pagination (band 7)."""
import json
from decimal import Decimal, InvalidOperation

from flask import request

import clock
import response
from errors import ApiError

_MISSING = object()


def bad(message):
    raise ApiError("ERR_INVALID_REQUEST", message)


def body():
    raw = request.get_data(cache=True)
    if raw is None or not raw.strip():
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"), parse_float=Decimal)
    except (ValueError, UnicodeDecodeError):
        bad("Request body is not valid JSON")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object")
    return parsed


def _present(data, name):
    value = data.get(name, _MISSING)
    if value is _MISSING or value is None:
        return _MISSING
    return value


def _numeric(value, name):
    if isinstance(value, bool) or not isinstance(value, (int, Decimal)):
        bad("Field %s must be a number" % name)
    try:
        return Decimal(value) if isinstance(value, int) else value
    except InvalidOperation:
        bad("Field %s must be a number" % name)


def _scale_ok(value, places=2):
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        return False
    return -exponent <= places


# ---------------------------------------------------------------- strings ----

def opt_str(data, name, min_len=None, max_len=None, default=None):
    value = _present(data, name)
    if value is _MISSING:
        return default
    if not isinstance(value, str):
        bad("Field %s must be a string" % name)
    if min_len is not None and len(value) < min_len:
        bad("Field %s is shorter than %d characters" % (name, min_len))
    if max_len is not None and len(value) > max_len:
        bad("Field %s is longer than %d characters" % (name, max_len))
    return value


def req_str(data, name, min_len=1, max_len=None):
    value = _present(data, name)
    if value is _MISSING:
        bad("Field %s is required" % name)
    return opt_str(data, name, min_len=min_len, max_len=max_len)


def req_enum(data, name, allowed):
    value = _present(data, name)
    if value is _MISSING:
        bad("Field %s is required" % name)
    if not isinstance(value, str) or value not in allowed:
        bad("Field %s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def opt_enum(data, name, allowed, default=None):
    value = _present(data, name)
    if value is _MISSING:
        return default
    if not isinstance(value, str) or value not in allowed:
        bad("Field %s must be one of %s" % (name, ", ".join(sorted(allowed))))
    return value


def opt_bool(data, name, default=None):
    value = _present(data, name)
    if value is _MISSING:
        return default
    if not isinstance(value, bool):
        bad("Field %s must be a boolean" % name)
    return value


def req_bool(data, name):
    value = _present(data, name)
    if value is _MISSING:
        bad("Field %s is required" % name)
    return opt_bool(data, name)


# --------------------------------------------------------------- numerics ----

def opt_int(data, name, minimum=None, maximum=None, default=None):
    value = _present(data, name)
    if value is _MISSING:
        return default
    if isinstance(value, bool) or not isinstance(value, int):
        bad("Field %s must be an integer" % name)
    if minimum is not None and value < minimum:
        bad("Field %s must be at least %d" % (name, minimum))
    if maximum is not None and value > maximum:
        bad("Field %s must be at most %d" % (name, maximum))
    return value


def req_int(data, name, minimum=None, maximum=None):
    value = _present(data, name)
    if value is _MISSING:
        bad("Field %s is required" % name)
    return opt_int(data, name, minimum=minimum, maximum=maximum)


def opt_money(data, name, minimum=Decimal("0"), exclusive_min=False, default=None):
    value = _present(data, name)
    if value is _MISSING:
        return default
    value = _numeric(value, name)
    if not _scale_ok(value, 2):
        bad("Field %s carries more than two decimal places" % name)
    if minimum is not None:
        if exclusive_min and value <= minimum:
            bad("Field %s must be greater than %s" % (name, minimum))
        if not exclusive_min and value < minimum:
            bad("Field %s must be at least %s" % (name, minimum))
    return value


def req_money(data, name, minimum=Decimal("0"), exclusive_min=False):
    value = _present(data, name)
    if value is _MISSING:
        bad("Field %s is required" % name)
    return opt_money(data, name, minimum=minimum, exclusive_min=exclusive_min)


def opt_pct(data, name, low=Decimal("0"), high=None, default=None):
    value = _present(data, name)
    if value is _MISSING:
        return default
    value = _numeric(value, name)
    if low is not None and value < low:
        bad("Field %s must be at least %s" % (name, low))
    if high is not None and value > high:
        bad("Field %s must be at most %s" % (name, high))
    return value


def req_pct(data, name, low=Decimal("0"), high=None):
    value = _present(data, name)
    if value is _MISSING:
        bad("Field %s is required" % name)
    return opt_pct(data, name, low=low, high=high)


# -------------------------------------------------------------- temporals ----

def opt_instant(data, name, default=None):
    value = _present(data, name)
    if value is _MISSING:
        return default
    try:
        return clock.parse_instant(value)
    except ValueError:
        bad("Field %s must be an ISO 8601 UTC timestamp" % name)


def req_instant(data, name):
    value = _present(data, name)
    if value is _MISSING:
        bad("Field %s is required" % name)
    return opt_instant(data, name)


def opt_date(data, name, default=None):
    value = _present(data, name)
    if value is _MISSING:
        return default
    try:
        return clock.parse_date(value)
    except ValueError:
        bad("Field %s must be a YYYY-MM-DD date" % name)


def req_date(data, name):
    value = _present(data, name)
    if value is _MISSING:
        bad("Field %s is required" % name)
    return opt_date(data, name)


# ------------------------------------------------- cancellation schedule -----

def _one_tier(item, name):
    if not isinstance(item, dict):
        bad("Field %s entries must be objects" % name)
    days = item.get("days_before_arrival_min")
    fee = item.get("fee_pct")
    if isinstance(days, bool) or not isinstance(days, int):
        bad("Field %s requires an integer days_before_arrival_min" % name)
    if days < 0:
        bad("Field %s requires a non-negative days_before_arrival_min" % name)
    fee = _numeric(fee, "%s.fee_pct" % name)
    if fee < 0:
        bad("Field %s requires a non-negative fee_pct" % name)
    return {"days_before_arrival_min": days, "fee_pct": fee}


def opt_schedule(data, name, default=None):
    value = _present(data, name)
    if value is _MISSING:
        return default
    if not isinstance(value, list) or not value:
        bad("Field %s must be a non-empty array of tiers" % name)
    return [_one_tier(item, name) for item in value]


def req_schedule(data, name):
    value = _present(data, name)
    if value is _MISSING:
        bad("Field %s is required" % name)
    return opt_schedule(data, name)


def dump_schedule(schedule):
    if schedule is None:
        return None
    return [
        {
            "days_before_arrival_min": tier["days_before_arrival_min"],
            "fee_pct": float(tier["fee_pct"]),
        }
        for tier in schedule
    ]


# ------------------------------------------------------- query parameters ----

def enum_filter(name, allowed):
    """Unrecognized enum filter values are a request-shape error (2.3)."""
    raw = request.args.get(name)
    if raw is None:
        return None
    if raw not in allowed:
        bad("Query parameter %s has an unrecognized value" % name)
    return raw


def str_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    return raw


def bool_filter(name):
    raw = request.args.get(name)
    if raw is None:
        return None
    lowered = raw.strip().lower()
    if lowered in ("true", "1"):
        return True
    if lowered in ("false", "0"):
        return False
    bad("Query parameter %s must be a boolean" % name)


def int_filter(name):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        bad("Query parameter %s must be an integer" % name)


def pagination():
    args = request.args
    limit = response.LIMIT_DEFAULT
    offset = response.OFFSET_DEFAULT
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    if raw_limit is not None:
        try:
            limit = int(raw_limit.strip())
        except (ValueError, AttributeError):
            raise ApiError("ERR_INVALID_PAGINATION", "limit must be an integer")
        if limit < response.LIMIT_MIN or limit > response.LIMIT_MAX:
            raise ApiError("ERR_INVALID_PAGINATION", "limit is out of range")
    if raw_offset is not None:
        try:
            offset = int(raw_offset.strip())
        except (ValueError, AttributeError):
            raise ApiError("ERR_INVALID_PAGINATION", "offset must be an integer")
        if offset < 0:
            raise ApiError("ERR_INVALID_PAGINATION", "offset must not be negative")
    return limit, offset


def page(rows, limit, offset, serializer):
    total = len(rows)
    window = rows[offset:offset + limit]
    return response.collection([serializer(r) for r in window], limit, offset, total)
