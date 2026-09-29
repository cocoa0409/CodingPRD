"""Payload-shape validation -- PRD 2.10 rule 12 (ERR_INVALID_REQUEST, 422).

"Every required field present, every value of its declared JSON type, every
enum value drawn from its declared member set, every number inside its declared
range and decimal width, every timestamp parseable as an ISO 8601 UTC instant,
`limit` within 1 to 100 inclusive, `offset` not negative."

JSON floats are parsed into ``Decimal`` so the literal decimal width written by
the client is preserved exactly and can be checked (PRD 2.7).
"""

import json
from decimal import Decimal, InvalidOperation

from flask import request

from errors import fail
from store import parse_date_only, parse_ts

_MISSING = object()


def read_body(required=True):
    """Parse the JSON body, preserving decimal widths.

    ``required=False`` is used for the operations that declare no input at all;
    those tolerate an absent or empty body.
    """
    raw = request.get_data(cache=True, as_text=True)
    if raw is None or raw.strip() == "":
        if required:
            fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
        return {}
    try:
        parsed = json.loads(raw, parse_float=Decimal)
    except (ValueError, InvalidOperation):
        if required:
            fail("ERR_INVALID_REQUEST", "The request body is not valid JSON.")
        return {}
    if parsed is None:
        if required:
            fail("ERR_INVALID_REQUEST", "A JSON object body is required.")
        return {}
    if not isinstance(parsed, dict):
        if required:
            fail("ERR_INVALID_REQUEST", "The request body must be a JSON object.")
        return {}
    return parsed


def _present(body, key):
    return key in body and body[key] is not None


def _bad(key, why):
    fail("ERR_INVALID_REQUEST", "Field '%s' %s." % (key, why))


def v_string(body, key, required=True, min_len=None, max_len=None, pattern=None, default=None):
    if not _present(body, key):
        if required:
            _bad(key, "is required")
        return default
    value = body[key]
    if not isinstance(value, str):
        _bad(key, "must be a string")
    if min_len is not None and len(value) < min_len:
        _bad(key, "must be at least %d characters" % min_len)
    if max_len is not None and len(value) > max_len:
        _bad(key, "must be at most %d characters" % max_len)
    if pattern is not None and not pattern.match(value):
        _bad(key, "does not match the required format")
    return value


def v_bool(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            _bad(key, "is required")
        return default
    value = body[key]
    if not isinstance(value, bool):
        _bad(key, "must be a boolean")
    return value


def v_int(body, key, required=True, minimum=None, maximum=None, default=None):
    if not _present(body, key):
        if required:
            _bad(key, "is required")
        return default
    value = body[key]
    if isinstance(value, bool) or not isinstance(value, int):
        _bad(key, "must be an integer")
    if minimum is not None and value < minimum:
        _bad(key, "must be at least %s" % minimum)
    if maximum is not None and value > maximum:
        _bad(key, "must be at most %s" % maximum)
    return value


def _decimal_places(value):
    exponent = value.as_tuple().exponent
    if not isinstance(exponent, int):
        return None
    return max(0, -exponent)


def v_number(body, key, required=True, minimum=None, maximum=None, max_dp=None, default=None):
    """A JSON number: integer or float.  ``max_dp`` bounds the decimal width."""
    if not _present(body, key):
        if required:
            _bad(key, "is required")
        return default
    value = body[key]
    if isinstance(value, bool):
        _bad(key, "must be a number")
    if isinstance(value, int):
        value = Decimal(value)
    elif isinstance(value, Decimal):
        if not value.is_finite():
            _bad(key, "must be a finite number")
    elif isinstance(value, float):
        value = Decimal(repr(value))
    else:
        _bad(key, "must be a number")
    if max_dp is not None:
        places = _decimal_places(value)
        if places is None or places > max_dp:
            _bad(key, "carries at most %d decimal places" % max_dp)
    if minimum is not None and value < Decimal(str(minimum)):
        _bad(key, "must be at least %s" % minimum)
    if maximum is not None and value > Decimal(str(maximum)):
        _bad(key, "must be at most %s" % maximum)
    return value


def v_enum(body, key, members, required=True, default=None):
    if not _present(body, key):
        if required:
            _bad(key, "is required")
        return default
    value = body[key]
    if not isinstance(value, str):
        _bad(key, "must be a string")
    if value not in members:
        _bad(key, "must be one of %s" % ", ".join(members))
    return value


def v_instant(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            _bad(key, "is required")
        return default
    value = body[key]
    if not isinstance(value, str):
        _bad(key, "must be a string")
    parsed = parse_ts(value)
    if parsed is None:
        _bad(key, "must be an ISO 8601 UTC instant")
    return parsed


def v_date(body, key, required=True, default=None):
    if not _present(body, key):
        if required:
            _bad(key, "is required")
        return default
    value = body[key]
    if not isinstance(value, str):
        _bad(key, "must be a string")
    if parse_date_only(value) is None:
        _bad(key, "must be a calendar date in YYYY-MM-DD form")
    return value


def v_enum_array(body, key, members, required=False, default=None, distinct=True):
    if not _present(body, key):
        if required:
            _bad(key, "is required")
        return list(default) if default is not None else None
    value = body[key]
    if not isinstance(value, list):
        _bad(key, "must be an array")
    out = []
    for item in value:
        if not isinstance(item, str) or item not in members:
            _bad(key, "must contain only members of %s" % ", ".join(members))
        if distinct and item in out:
            _bad(key, "must contain distinct members")
        out.append(item)
    return out


# ---------------------------------------------------------------- query params

def q_pagination():
    """PRD 2.3: limit defaults to 10 (1..100); offset defaults to 0 (>= 0)."""
    limit = _q_int("limit", 10)
    offset = _q_int("offset", 0)
    if limit < 1 or limit > 100:
        fail("ERR_INVALID_REQUEST", "Field 'limit' must be between 1 and 100 inclusive.")
    if offset < 0:
        fail("ERR_INVALID_REQUEST", "Field 'offset' must not be negative.")
    return limit, offset


def _q_int(name, default):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    try:
        return int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)


def q_int(name, required=True, minimum=None, maximum=None, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            fail("ERR_INVALID_REQUEST", "Query parameter '%s' is required." % name)
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be an integer." % name)
    if minimum is not None and value < minimum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be at least %s." % (name, minimum))
    if maximum is not None and value > maximum:
        fail("ERR_INVALID_REQUEST", "Query parameter '%s' must be at most %s." % (name, maximum))
    return value


def q_instant(name, required=True, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        if required:
            fail("ERR_INVALID_REQUEST", "Query parameter '%s' is required." % name)
        return default
    parsed = parse_ts(raw)
    if parsed is None:
        fail(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be an ISO 8601 UTC instant." % name,
        )
    return parsed


def q_enum(name, members, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    if raw not in members:
        fail(
            "ERR_INVALID_REQUEST",
            "Query parameter '%s' must be one of %s." % (name, ", ".join(members)),
        )
    return raw


def q_string(name, default=None):
    raw = request.args.get(name)
    if raw is None or raw == "":
        return default
    return raw
