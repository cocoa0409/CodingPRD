"""Payload-shape validation (ladder step 4 -> ERR_INVALID_REQUEST)."""
import json
import re
from datetime import datetime, timezone

from flask import request

import clock
import envelope
from errors import ApiError

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def bad(message="The request payload is malformed or violates a declared constraint."):
    return ApiError("ERR_INVALID_REQUEST", message)


def json_body():
    """Parse the request body, tolerating an absent body as an empty object."""
    raw = request.get_data(cache=True) or b""
    if not raw.strip():
        return {}
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except Exception:
        raise bad("Request body is not valid JSON.")
    if parsed is None:
        return {}
    if not isinstance(parsed, dict):
        raise bad("Request body must be a JSON object.")
    return parsed


def raw_field(body, key):
    """Read a field before shape validation (used by target-state ownership)."""
    value = body.get(key)
    if isinstance(value, str):
        return value
    return None


def present(body, key):
    return key in body and body.get(key) is not None


def req_str(body, key, min_len=1, max_len=None):
    if key not in body:
        raise bad("Field '%s' is required." % key)
    value = body.get(key)
    if not isinstance(value, str):
        raise bad("Field '%s' must be a string." % key)
    if len(value) < min_len:
        raise bad("Field '%s' is too short." % key)
    if max_len is not None and len(value) > max_len:
        raise bad("Field '%s' is too long." % key)
    return value


def opt_str(body, key, default=None, min_len=1, max_len=None):
    if key not in body or body.get(key) is None:
        return default
    return req_str(body, key, min_len, max_len)


def req_enum(body, key, allowed):
    value = req_str(body, key, 1, None)
    if value not in allowed:
        raise bad("Field '%s' is not one of the accepted values." % key)
    return value


def opt_enum(body, key, allowed, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_enum(body, key, allowed)


def _int_value(key, value, minimum, maximum):
    if isinstance(value, bool) or not isinstance(value, int):
        raise bad("Field '%s' must be an integer." % key)
    if minimum is not None and value < minimum:
        raise bad("Field '%s' is below its minimum." % key)
    if maximum is not None and value > maximum:
        raise bad("Field '%s' is above its maximum." % key)
    return value


def req_int(body, key, minimum=None, maximum=None):
    if key not in body:
        raise bad("Field '%s' is required." % key)
    return _int_value(key, body.get(key), minimum, maximum)


def opt_int(body, key, default=None, minimum=None, maximum=None):
    if key not in body or body.get(key) is None:
        return default
    return _int_value(key, body.get(key), minimum, maximum)


def req_int_in(body, key, allowed):
    value = req_int(body, key)
    if value not in allowed:
        raise bad("Field '%s' is not one of the accepted values." % key)
    return value


def opt_int_in(body, key, allowed, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_int_in(body, key, allowed)


def opt_bool(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    value = body.get(key)
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % key)
    return value


def req_bool(body, key):
    if key not in body:
        raise bad("Field '%s' is required." % key)
    value = body.get(key)
    if not isinstance(value, bool):
        raise bad("Field '%s' must be a boolean." % key)
    return value


def req_dt(body, key):
    if key not in body:
        raise bad("Field '%s' is required." % key)
    value = clock.parse_dt(body.get(key))
    if value is None:
        raise bad("Field '%s' must be an ISO 8601 instant." % key)
    return value


def opt_dt(body, key, default=None):
    if key not in body or body.get(key) is None:
        return default
    return req_dt(body, key)


def req_date(body, key):
    value = req_str(body, key, 1, None)
    if not _DATE_RE.match(value):
        raise bad("Field '%s' must be a YYYY-MM-DD calendar date." % key)
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise bad("Field '%s' is not a real calendar date." % key)
    return value


def req_str_list(body, key, min_items, max_items, unique=False, max_len=None):
    if key not in body:
        raise bad("Field '%s' is required." % key)
    value = body.get(key)
    if not isinstance(value, list):
        raise bad("Field '%s' must be an array." % key)
    if len(value) < min_items or len(value) > max_items:
        raise bad("Field '%s' carries an unaccepted number of elements." % key)
    for item in value:
        if not isinstance(item, str) or len(item) < 1:
            raise bad("Every element of '%s' must be a non-empty string." % key)
        if max_len is not None and len(item) > max_len:
            raise bad("An element of '%s' is too long." % key)
    if unique and len(set(value)) != len(value):
        raise bad("Elements of '%s' must be unique." % key)
    return value


DOMAIN_KEYS = ("adl", "cognition", "medical_complexity", "social_support",
               "safety", "finances")


def req_domain_scores(body, key="domain_scores"):
    if key not in body:
        raise bad("Field 'domain_scores' is required.")
    value = body.get(key)
    if not isinstance(value, dict):
        raise bad("Field 'domain_scores' must be an object.")
    if set(value.keys()) != set(DOMAIN_KEYS):
        raise bad("domain_scores must carry exactly the six declared keys.")
    out = {}
    for name in DOMAIN_KEYS:
        item = value.get(name)
        if isinstance(item, bool) or not isinstance(item, int):
            raise bad("domain_scores.%s must be an integer." % name)
        if item < 0 or item > 5:
            raise bad("domain_scores.%s must lie between 0 and 5." % name)
        out[name] = item
    return out


def _query_int(name, default, minimum, maximum):
    args = request.args
    if name not in args:
        return default
    raw = args.get(name)
    if raw is None or raw.strip() == "":
        raise bad("Query parameter '%s' is malformed." % name)
    try:
        value = int(raw.strip())
    except ValueError:
        raise bad("Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        raise bad("Query parameter '%s' is out of range." % name)
    if maximum is not None and value > maximum:
        raise bad("Query parameter '%s' is out of range." % name)
    return value


def paging():
    limit = _query_int("limit", envelope.PAGE_LIMIT_DEFAULT,
                       envelope.PAGE_LIMIT_MIN, envelope.PAGE_LIMIT_MAX)
    offset = _query_int("offset", envelope.PAGE_OFFSET_DEFAULT, 0, None)
    return limit, offset


def filters(names):
    out = {}
    for name in names:
        if name in request.args:
            out[name] = request.args.get(name)
    return out
