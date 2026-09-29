"""Request shape validation (ladder step 3). Unknown body fields are ignored."""
from decimal import Decimal, InvalidOperation

from flask import request

from common import D, parse_dt
from errors import ApiError


def bad(field, detail):
    raise ApiError("ERR_INVALID_REQUEST", "%s %s" % (field, detail))


def body():
    if not request.data:
        return {}
    try:
        parsed = request.get_json(force=True, silent=True)
    except Exception:
        parsed = None
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise ApiError("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
    return parsed


def _present(payload, field, required):
    if field not in payload or payload[field] is None:
        if required:
            bad(field, "is required.")
        return False
    return True


def req_str(payload, field, required=True, min_len=None, max_len=None, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, str):
        bad(field, "must be a string.")
    if min_len is not None and len(value) < min_len:
        bad(field, "must be at least %d characters." % min_len)
    if max_len is not None and len(value) > max_len:
        bad(field, "must be at most %d characters." % max_len)
    return value


def req_bool(payload, field, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, bool):
        bad(field, "must be a boolean.")
    return value


def req_int(payload, field, required=True, minimum=None, maximum=None, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int):
        bad(field, "must be an integer.")
    if minimum is not None and value < minimum:
        bad(field, "must be at least %s." % minimum)
    if maximum is not None and value > maximum:
        bad(field, "must be at most %s." % maximum)
    return value


def req_num(payload, field, required=True, minimum=None, maximum=None, default=None):
    """A number field, returned as a Decimal so no float noise ever enters."""
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        bad(field, "must be a number.")
    try:
        dec = D(value)
    except (InvalidOperation, TypeError, ValueError):
        bad(field, "must be a number.")
    if not dec.is_finite():
        bad(field, "must be a finite number.")
    if minimum is not None and dec < D(minimum):
        bad(field, "must be at least %s." % minimum)
    if maximum is not None and dec > D(maximum):
        bad(field, "must be at most %s." % maximum)
    return dec


def req_enum(payload, field, members, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if isinstance(value, bool) or value not in members:
        bad(field, "must be one of %s." % ", ".join(str(m) for m in members))
    return value


def req_int_enum(payload, field, members, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if isinstance(value, bool) or not isinstance(value, int) or value not in members:
        bad(field, "must be one of %s." % ", ".join(str(m) for m in members))
    return value


def req_dt(payload, field, required=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, str):
        bad(field, "must be an ISO 8601 instant.")
    parsed = parse_dt(value)
    if parsed is None:
        bad(field, "must be an ISO 8601 instant.")
    return parsed


def req_str_array(payload, field, required=True, non_empty=True, default=None):
    if not _present(payload, field, required):
        return default
    value = payload[field]
    if not isinstance(value, list):
        bad(field, "must be an array of strings.")
    if non_empty and len(value) == 0:
        bad(field, "must be a non-empty array.")
    for item in value:
        if not isinstance(item, str):
            bad(field, "must be an array of strings.")
    return list(value)
