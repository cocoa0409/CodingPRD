"""Request body shape validation (priority 3 -> ERR_INVALID_REQUEST, 400)
and pagination parsing (PRD 2.3: limit default 10, bounds 1..100; offset
default 0)."""
from flask import request

from errors import invalid_request
from store import parse_dt


def get_body():
    """Return the JSON body as a dict; absent body is {}. A present but
    non-object body is a shape error."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        invalid_request("request body must be a JSON object")
    return data


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def req_field(body, name):
    if name not in body or body[name] is None:
        invalid_request("missing required field: %s" % name)
    return body[name]


def req_str(body, name):
    v = req_field(body, name)
    if not isinstance(v, str) or not v:
        invalid_request("field %s must be a non-empty string" % name)
    return v


def opt_str(body, name):
    if name not in body or body[name] is None:
        return None
    if not isinstance(body[name], str):
        invalid_request("field %s must be a string" % name)
    return body[name]


def req_int(body, name, lo=None, hi=None):
    v = req_field(body, name)
    if not _is_int(v):
        invalid_request("field %s must be an integer" % name)
    if lo is not None and v < lo:
        invalid_request("field %s must be >= %d" % (name, lo))
    if hi is not None and v > hi:
        invalid_request("field %s must be <= %d" % (name, hi))
    return v


def opt_int(body, name, lo=None, hi=None):
    if name not in body or body[name] is None:
        return None
    if not _is_int(body[name]):
        invalid_request("field %s must be an integer" % name)
    v = body[name]
    if lo is not None and v < lo:
        invalid_request("field %s must be >= %d" % (name, lo))
    if hi is not None and v > hi:
        invalid_request("field %s must be <= %d" % (name, hi))
    return v


def req_bool(body, name):
    v = req_field(body, name)
    if not isinstance(v, bool):
        invalid_request("field %s must be a boolean" % name)
    return v


def req_enum(body, name, choices):
    v = req_field(body, name)
    if not isinstance(v, str) or v not in choices:
        invalid_request("field %s must be one of %s" % (name, "|".join(choices)))
    return v


def opt_enum(body, name, choices):
    if name not in body or body[name] is None:
        return None
    return req_enum(body, name, choices)


def req_dt(body, name):
    v = req_field(body, name)
    dt = parse_dt(v)
    if dt is None:
        invalid_request("field %s must be an ISO 8601 datetime" % name)
    return dt


def parse_pagination():
    """limit: default 10, bounds 1..100; offset: default 0, >= 0."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    if raw_limit is None:
        limit = 10
    else:
        try:
            limit = int(raw_limit.strip())
        except (TypeError, ValueError, AttributeError):
            invalid_request("limit must be an integer")
        if limit < 1 or limit > 100:
            invalid_request("limit must be between 1 and 100")
    if raw_offset is None:
        offset = 0
    else:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            invalid_request("offset must be an integer")
        if offset < 0:
            invalid_request("offset must be >= 0")
    return limit, offset


def opt_query(name):
    v = request.args.get(name)
    return v if v else None
