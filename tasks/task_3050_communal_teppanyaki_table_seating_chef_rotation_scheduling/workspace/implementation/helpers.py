"""Request-body parsing, declared-field coercion and pagination plumbing."""
from flask import request

import constants as C
import db
from errors import fail

_MISSING = object()


def payload():
    """Return the JSON body as a dict. An absent body reads as an empty dict."""
    if not request.data:
        return {}
    data = request.get_json(silent=True)
    if data is None:
        fail("ERR_INVALID_REQUEST", "Request body is not valid JSON.")
    if not isinstance(data, dict):
        fail("ERR_INVALID_REQUEST", "Request body must be a JSON object.")
    return data


def field(body, name, required=True, default=None):
    if name in body and body[name] is not None:
        return body[name]
    if required:
        fail("ERR_INVALID_REQUEST", "Missing required field: %s" % name)
    return default


def as_string(body, name, required=True, default=None, enum=None, allow_empty=False):
    value = field(body, name, required=required, default=default)
    if value is None:
        return None
    if not isinstance(value, str) or (not allow_empty and value == ""):
        fail("ERR_INVALID_REQUEST", "Field %s must be a string." % name)
    if enum is not None and value not in enum:
        fail("ERR_INVALID_REQUEST",
             "Field %s must be one of %s." % (name, ", ".join(enum)))
    return value


def as_int(body, name, required=True, default=None, minimum=None, maximum=None):
    value = field(body, name, required=required, default=default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        fail("ERR_INVALID_REQUEST", "Field %s must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Field %s must be at least %d." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Field %s must be at most %d." % (name, maximum))
    return value


def as_number(body, name, required=True, default=None):
    value = field(body, name, required=required, default=default)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail("ERR_INVALID_REQUEST", "Field %s must be a number." % name)
    return value


def as_datetime(body, name, required=True, default=None):
    value = field(body, name, required=required, default=default)
    if value is None:
        return None
    parsed = db.parse_dt(value)
    if parsed is None:
        fail("ERR_INVALID_REQUEST", "Field %s must be an ISO 8601 instant." % name)
    return parsed


def as_bool(body, name, required=True, default=None):
    value = field(body, name, required=required, default=default)
    if value is None:
        return None
    if not isinstance(value, bool):
        fail("ERR_INVALID_REQUEST", "Field %s must be a boolean." % name)
    return value


def pagination():
    """Read limit/offset, enforcing the declared band (defaults 10/0, min 1, max 100)."""
    raw_limit = request.args.get("limit")
    raw_offset = request.args.get("offset")
    limit = C_LIMIT_DEFAULT
    offset = 0
    if raw_limit is not None:
        try:
            limit = int(raw_limit)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "limit must be an integer.")
    if raw_offset is not None:
        try:
            offset = int(raw_offset)
        except (TypeError, ValueError):
            fail("ERR_INVALID_REQUEST", "offset must be an integer.")
    if limit < 1 or limit > 100:
        fail("ERR_INVALID_REQUEST", "limit must be between 1 and 100.")
    if offset < 0:
        fail("ERR_INVALID_REQUEST", "offset must not be negative.")
    return limit, offset


C_LIMIT_DEFAULT = 10


def q(name):
    value = request.args.get(name)
    return value if value not in (None, "") else None


def filter_rows(rows, **criteria):
    out = []
    for row in rows:
        keep = True
        for key, value in criteria.items():
            if value is None:
                continue
            if row.get(key) != value:
                keep = False
                break
        if keep:
            out.append(row)
    return out


def list_response(rows, serializer=db.public, sort_key=None):
    limit, offset = pagination()
    if sort_key is not None:
        ordered = sorted(rows, key=sort_key)
    else:
        ordered = db.sorted_by_created(rows)
    total = len(ordered)
    page = ordered[offset:offset + limit]
    return [serializer(r) for r in page], {
        "limit": limit,
        "offset": offset,
        "total_count": total,
        "has_more": offset + limit < total,
    }