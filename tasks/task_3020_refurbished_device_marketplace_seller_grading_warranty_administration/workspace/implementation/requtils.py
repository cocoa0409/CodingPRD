"""Request-body and query-parameter helpers.

Priority 2 of PRD §2.11 -- request-shape validation (`ERR_INVALID_REQUEST`).
"""

import re

from flask import request

from errors import fail
from vocab import DEFAULT_LIMIT, DEFAULT_OFFSET, MAX_LIMIT, MIN_LIMIT

HEX64 = re.compile(r"\A[0-9a-f]{64}\Z")
IMEI15 = re.compile(r"\A[0-9]{15}\Z")
COUNTRY2 = re.compile(r"\A[A-Z]{2}\Z")


def body():
    """The request body as a dict; an absent/empty body is an empty dict."""
    data = request.get_json(silent=True)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise fail("ERR_INVALID_REQUEST")
    return data


def is_present(data, key):
    return key in data and data[key] is not None


def required(data, key):
    if not is_present(data, key):
        raise fail("ERR_INVALID_REQUEST", "The field '%s' is required." % key)
    return data[key]


def as_int(value, field="value"):
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value.is_integer():
            return int(value)
        raise fail("ERR_INVALID_REQUEST", "The field '%s' must be an integer." % field)
    return value


def as_str(value, field="value"):
    if not isinstance(value, str) or value == "":
        raise fail("ERR_INVALID_REQUEST", "The field '%s' must be a non-empty string." % field)
    return value


def opt_str(data, key):
    value = data.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise fail("ERR_INVALID_REQUEST", "The field '%s' must be a string." % key)
    return value


def check_enum(value, allowed, field):
    if value not in allowed:
        raise fail(
            "ERR_INVALID_REQUEST",
            "The field '%s' must be one of %s." % (field, ", ".join(allowed)),
        )
    return value


def range_int(value, field, low=None, high=None):
    value = as_int(value, field)
    if low is not None and value < low:
        raise fail("ERR_INVALID_REQUEST", "The field '%s' must be at least %d." % (field, low))
    if high is not None and value > high:
        raise fail("ERR_INVALID_REQUEST", "The field '%s' must be at most %d." % (field, high))
    return value


def hex64(value, field):
    if not isinstance(value, str) or not HEX64.match(value):
        raise fail(
            "ERR_INVALID_REQUEST",
            "The field '%s' must be exactly 64 lowercase hexadecimal characters." % field,
        )
    return value


def is_hex64(value):
    return isinstance(value, str) and bool(HEX64.match(value))


def pagination():
    """limit/offset with the scaffold's defaults and 1..100 clamp."""
    limit_raw = request.args.get("limit")
    offset_raw = request.args.get("offset")
    limit = DEFAULT_LIMIT
    offset = DEFAULT_OFFSET
    if limit_raw is not None:
        try:
            limit = int(limit_raw)
        except (TypeError, ValueError):
            raise fail("ERR_INVALID_REQUEST", "The 'limit' parameter must be an integer.")
        if limit < MIN_LIMIT or limit > MAX_LIMIT:
            raise fail("ERR_INVALID_REQUEST", "The 'limit' parameter must be between 1 and 100.")
    if offset_raw is not None:
        try:
            offset = int(offset_raw)
        except (TypeError, ValueError):
            raise fail("ERR_INVALID_REQUEST", "The 'offset' parameter must be an integer.")
        if offset < 0:
            raise fail("ERR_INVALID_REQUEST", "The 'offset' parameter must not be negative.")
    return limit, offset


def filter_eq(rows, kwargs):
    """Apply optional equality filters supplied as query parameters."""
    out = rows
    for key, value in kwargs.items():
        if value is None:
            continue
        out = [row for row in out if row.get(key) == value]
    return out


def paginate(rows, limit, offset):
    return rows[offset:offset + limit]


def created_asc(rows):
    """PRD §2.3 default ordering: creation timestamp ascending.

    Ties are broken by the server-side insertion sequence so that the order is
    totally deterministic and never depends on a random id.
    """
    return sorted(rows, key=lambda r: (r.get("created_at", ""), r.get("_seq", 0)))