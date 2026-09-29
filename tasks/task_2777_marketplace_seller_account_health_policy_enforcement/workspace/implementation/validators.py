"""Request-shape validation (PRD 2.8 step 7) and pagination (PRD 2.3)."""

import json
from decimal import Decimal, InvalidOperation

from flask import request

import clock
import constants as C
from errors import ApiError

MISSING = object()


def bad(message=None, error_id="ERR_INVALID_REQUEST"):
    raise ApiError(error_id, message)


def body():
    """Parsed JSON object, or {} when the request carried no body at all."""
    raw = request.get_data(cache=True)
    if raw is None or raw.strip() == b"":
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        bad("Request body is not valid JSON.")
    if not isinstance(parsed, dict):
        bad("Request body must be a JSON object.")
    return parsed


def _as_int(raw):
    if isinstance(raw, bool):
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(raw) if float(raw).is_integer() else None
    return None


def _int_query(raw):
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def pagination():
    limit = C.PAGE_LIMIT_DEFAULT
    offset = C.PAGE_OFFSET_DEFAULT
    if "limit" in request.args:
        limit = _int_query(request.args.get("limit"))
        if limit is None or limit < C.PAGE_LIMIT_MIN or limit > C.PAGE_LIMIT_MAX:
            bad("'limit' must be an integer between 1 and 100.")
    if "offset" in request.args:
        offset = _int_query(request.args.get("offset"))
        if offset is None or offset < 0:
            bad("'offset' must be a non-negative integer.")
    return limit, offset


def present(data, key):
    return key in data and data[key] is not None


def req_str(data, key, min_len=None, max_len=None, trim=False, error_id="ERR_INVALID_REQUEST"):
    if not present(data, key):
        bad("'%s' is required." % key, error_id)
    value = data[key]
    if not isinstance(value, str):
        bad("'%s' must be a string." % key, error_id)
    measured = value.strip() if trim else value
    if min_len is not None and len(measured) < min_len:
        bad("'%s' is shorter than %d characters." % (key, min_len), error_id)
    if max_len is not None and len(measured) > max_len:
        bad("'%s' is longer than %d characters." % (key, max_len), error_id)
    return value


def opt_str(data, key, min_len=None, max_len=None, trim=False, default=None,
            error_id="ERR_INVALID_REQUEST"):
    if not present(data, key):
        return default
    return req_str(data, key, min_len, max_len, trim, error_id)


def req_enum(data, key, allowed, error_id="ERR_INVALID_REQUEST"):
    if not present(data, key):
        bad("'%s' is required." % key, error_id)
    value = data[key]
    if not isinstance(value, str) or value not in allowed:
        bad("'%s' must be one of %s." % (key, ", ".join(allowed)), error_id)
    return value


def opt_enum(data, key, allowed, default=None, error_id="ERR_INVALID_REQUEST"):
    if not present(data, key):
        return default
    return req_enum(data, key, allowed, error_id)


def req_int(data, key, minimum=None, maximum=None, error_id="ERR_INVALID_REQUEST"):
    if not present(data, key):
        bad("'%s' is required." % key, error_id)
    value = _as_int(data[key])
    if value is None:
        bad("'%s' must be an integer." % key, error_id)
    if minimum is not None and value < minimum:
        bad("'%s' must be at least %d." % (key, minimum), error_id)
    if maximum is not None and value > maximum:
        bad("'%s' must be at most %d." % (key, maximum), error_id)
    return value


def opt_int(data, key, minimum=None, maximum=None, default=None,
            error_id="ERR_INVALID_REQUEST"):
    if not present(data, key):
        return default
    return req_int(data, key, minimum, maximum, error_id)


def req_bool(data, key, default=None, error_id="ERR_INVALID_REQUEST"):
    if not present(data, key):
        return default
    value = data[key]
    if not isinstance(value, bool):
        bad("'%s' must be a boolean." % key, error_id)
    return value


def req_decimal(data, key, places, minimum=None, maximum=None,
                error_id="ERR_INVALID_REQUEST"):
    if not present(data, key):
        bad("'%s' is required." % key, error_id)
    raw = data[key]
    if isinstance(raw, bool) or not isinstance(raw, (int, float, str)):
        bad("'%s' must be a number." % key, error_id)
    try:
        value = Decimal(str(raw))
    except (InvalidOperation, ValueError):
        bad("'%s' must be a number." % key, error_id)
    if not value.is_finite():
        bad("'%s' must be a finite number." % key, error_id)
    value = quantize(value, places)
    if minimum is not None and value < minimum:
        bad("'%s' is below the permitted minimum." % key, error_id)
    if maximum is not None and value > maximum:
        bad("'%s' is above the permitted maximum." % key, error_id)
    return value


def req_datetime(data, key, error_id="ERR_INVALID_REQUEST"):
    if not present(data, key):
        bad("'%s' is required." % key, error_id)
    if not isinstance(data[key], str):
        bad("'%s' must be an ISO 8601 UTC timestamp." % key, error_id)
    parsed = clock.parse_iso(data[key])
    if parsed is None:
        bad("'%s' must be an ISO 8601 UTC timestamp." % key, error_id)
    return parsed


def req_str_array(data, key, min_items, max_items, min_len, max_len,
                  error_id="ERR_INVALID_REQUEST"):
    if not present(data, key):
        bad("'%s' is required." % key, error_id)
    value = data[key]
    if not isinstance(value, list):
        bad("'%s' must be an array of strings." % key, error_id)
    if len(value) < min_items or len(value) > max_items:
        bad("'%s' must hold between %d and %d elements." % (key, min_items, max_items),
            error_id)
    for element in value:
        if not isinstance(element, str):
            bad("every element of '%s' must be a string." % key, error_id)
        if len(element) < min_len or len(element) > max_len:
            bad("every element of '%s' must be %d to %d characters."
                % (key, min_len, max_len), error_id)
    return list(value)


def quantize(value, places):
    from decimal import ROUND_HALF_UP
    exp = Decimal(1).scaleb(-places)
    return Decimal(value).quantize(exp, rounding=ROUND_HALF_UP)
