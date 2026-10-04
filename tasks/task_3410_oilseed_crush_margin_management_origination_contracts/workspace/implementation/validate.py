"""Request body/field validation helpers (shape rules -> ERR_INVALID_REQUEST)."""
from decimal import Decimal, InvalidOperation

from flask import request

from dates import parse_iso, valid_month
from errors import fail


def body_dict():
    b = request.get_json(silent=True)
    if b is None:
        return {}
    if not isinstance(b, dict):
        fail("ERR_INVALID_REQUEST", "request body must be a JSON object")
    return b


def to_decimal(v):
    if v is None or isinstance(v, bool) or not isinstance(v, (int, float, str)):
        return None
    try:
        d = Decimal(str(v))
    except InvalidOperation:
        return None
    if d.is_nan() or d.is_infinite():
        return None
    return d


def to_int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, float) and v.is_integer():
        return int(v)
    return None


def get_decimal(body, name):
    if name not in body or body[name] is None:
        return None
    d = to_decimal(body[name])
    if d is None:
        fail("ERR_INVALID_REQUEST", "%s must be a number" % name)
    return d


def req_decimal(body, name):
    d = get_decimal(body, name)
    if d is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    return d


def get_int(body, name):
    if name not in body or body[name] is None:
        return None
    i = to_int(body[name])
    if i is None:
        fail("ERR_INVALID_REQUEST", "%s must be an integer" % name)
    return i


def req_int(body, name):
    i = get_int(body, name)
    if i is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    return i


def get_str(body, name):
    if name not in body or body[name] is None:
        return None
    if not isinstance(body[name], str):
        fail("ERR_INVALID_REQUEST", "%s must be a string" % name)
    return body[name]


def req_str(body, name):
    s = get_str(body, name)
    if s is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    return s


def forbid_fields(body, names):
    for n in names:
        if n in body and body[n] is not None:
            fail("ERR_INVALID_REQUEST",
                 "%s is not permitted for this resource type" % n)


def req_datetime(body, name):
    if name not in body or body[name] is None:
        fail("ERR_INVALID_REQUEST", "%s is required" % name)
    dt = parse_iso(body[name])
    if dt is None:
        fail("ERR_INVALID_REQUEST", "%s must be an ISO 8601 datetime" % name)
    return dt


def req_month(body, name):
    s = req_str(body, name)
    if not valid_month(s):
        fail("ERR_INVALID_REQUEST", "%s must be in YYYY-MM format" % name)
    return s


def _query_int(raw):
    """Query-string parameters always arrive as strings; parse plain decimal
    integers, returning None for anything else (e.g. "abc", "2.5")."""
    try:
        return int(raw, 10)
    except (TypeError, ValueError):
        return None


def paginate(items):
    """limit: default 10, min 1, capped at 100; offset: default 0, min 0."""
    args = request.args
    raw_limit = args.get("limit")
    raw_offset = args.get("offset")
    limit = _query_int(raw_limit) if raw_limit is not None else 10
    offset = _query_int(raw_offset) if raw_offset is not None else 0
    if limit is None or offset is None:
        fail("ERR_INVALID_REQUEST", "limit/offset must be integers")
    if limit < 1 or offset < 0:
        fail("ERR_INVALID_REQUEST", "limit must be >= 1 and offset >= 0")
    if limit > 100:
        limit = 100
    total = len(items)
    return items[offset:offset + limit], limit, offset, total


def sort_created(items):
    return sorted(items, key=lambda r: r["_seq"])
